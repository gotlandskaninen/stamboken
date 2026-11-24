"""
Flask CLI for member registry operations.

Usage:
    flask members import <csv_path> [--dry-run | --counts-only]
    flask members billing-proposals --out <file> | --apply <file> --actor-user-id <id>
    flask members workspace-proposals <csv> --out <file> | --apply <file> --actor-user-id <id>
    flask members link-by-herd [--apply --actor-user-id <id> --plan <value>]
    flask members link-same-number [--apply --actor-user-id <id> --plan <value>]

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
- Except for friexemplar, a main member's address becomes a login address: when
  another person holds it, the whole group fails and is listed as an error.

`link-by-herd` links existing accounts to member rows through herd
ownership: the sole owner of herd G<Nr>/M<Nr> can match membership Nr's
main member by name, e-mail address or e-mail local part (mode "cli"). Other
cases are listed for the register manager. Plan only unless --apply.
"""

import csv
import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import click
from flask.cli import AppGroup
from peewee import DatabaseError, IntegrityError, fn
from utils.database import BILLING_FIELDS, DB_PROXY, Genebank, Herd, Member, Membership, User
from utils.herd_contact import link_herd
from utils.login_code import reserve_login_address
from utils.matrikel import (
    ANONYMIZED_FIRST_NAME,
    ANONYMIZED_LAST_NAME,
    ConfirmRequired,
    LinkError,
    add_person,
    is_anonymized,
    link_access_delta,
    link_member_user,
    new_membership,
    normalize_postal_code,
    parse_billing_fields,
    raise_counter_to,
    split_postal_address,
    write_matrikel_audit,
)
from utils.members import WORKSPACE_DOMAIN
from utils.membership_lifecycle import Status

from cli.billing_notes import parse_billing_note
from cli.proposal_file import proposal_cell, read_decisions, write_proposals

logger = logging.getLogger(__name__)

members_cli = AppGroup("members", help="Member registry operations.")


class _RowError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@members_cli.command("import")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Print the full import plan without writing.")
@click.option(
    "--counts-only",
    is_flag=True,
    help="Roll back the real import and print counts, error locations and herd warnings without personal data.",
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
        if counts_only:
            click.echo(f"Error: {len(file_errors)} file error(s)", err=True)
        for detail, diagnostic in file_errors:
            click.echo(f"Error: {diagnostic if counts_only else detail}", err=True)
        raise click.ClickException("filen avvisades — inga rader importerade")
    if counts_only:
        # nested atomic() blocks become savepoints: persons, links and the counter all roll back
        with DB_PROXY.atomic() as outer:
            report = _import(rows, errors, dry_run=False)
            outer.rollback()
        for line in _count_lines(report):
            click.echo(line)
        for warning in report["herd_warnings"]:
            click.echo(f"  warning: {warning.partition(' to membership ')[0]}", err=True)
        click.echo("(counts-only — rolled back, nothing written)")
    else:
        report = _import(rows, errors, dry_run)
        _print_report(report, dry_run)

    # Non-zero exit code when any rows errored — lets CI detect bad imports.
    if report["errors"]:
        for line in report["error_codes"] if counts_only else report["errors"]:
            click.echo(f"Error: {line}", err=True)
        if counts_only:
            raise click.ClickException(f"{len(report['errors'])} row(s) failed to import")
        raise click.ClickException(f"{len(report['errors'])} row(s) failed to import — see stderr for details")


def _import(rows: list[dict], errors: list[tuple[str, str]], dry_run: bool) -> dict:
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
        "errors": [detail for detail, _ in errors],
        "error_codes": [diagnostic for _, diagnostic in errors],  # only location and code for --counts-only
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
            report["error_codes"].append(f"Nr {nr}: {type(e).__name__}")

    for index, (name_key, group) in enumerate(friexemplar_groups.items(), start=1):
        try:
            _import_friexemplar_group(name_key, group, dry_run, report)
        except Exception as e:  # pylint: disable=broad-exception-caught
            report["errors"].append(f"friexemplar {name_key!r}: {e}")
            report["error_codes"].append(f"friexemplar {index}: {type(e).__name__}")
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


class _BadEncoding(ValueError):
    def __init__(self, line_num: int):
        super().__init__(f"line {line_num}")
        self.line_num = line_num


def _decoded_lines(f):
    for line_num, raw in enumerate(f, 1):
        try:
            yield raw.decode("utf-8-sig" if line_num == 1 else "utf-8")
        except UnicodeDecodeError as e:
            raise _BadEncoding(line_num) from e


def _read_rows(csv_path: str) -> tuple[list[dict], list[tuple[str, str]], list[tuple[str, str]]]:
    """Parse the CSV into normalized row dicts.

    Returns (rows, row_errors, file_errors). Each error pairs the original
    detail with a diagnostic safe for --counts-only. file_errors (no header row,
    duplicate columns, an address layout that is neither the legacy
    'Postadress' nor the split 'Postnummer'+'Postort') mean NOTHING may be
    written — the caller aborts before touching the counter.

    Lines before the header row (title/legend/count preamble in the raw
    export) and filler rows with at most the Nr cell filled (the
    year-statistics footer) are skipped. A row carrying any other data
    without a name still errors — that is corruption, not filler.
    """
    rows, errors, file_errors = [], [], []
    with open(csv_path, "rb") as f:
        # Decoded one physical line at a time, so a bad byte is reported on its own line (a text reader buffers
        # ahead). shortcut: a file with bare CR line ends reads as one line and fails as ogiltig-csv.
        reader = csv.reader(_decoded_lines(f))
        fieldnames = None
        layout = None
        while True:
            start_line = reader.line_num + 1
            try:
                cells = next(reader, None)
            except _BadEncoding as e:  # the message carries the byte: only the detail keeps it
                file_errors.append((f"rad {e.line_num}: {e.__cause__}", f"row {e.line_num}: ogiltig-teckenkodning"))
                return [], [], file_errors
            except csv.Error as e:  # the raw message can carry text from the file
                file_errors.append((f"rad {start_line}: {e}", f"row {start_line}: ogiltig-csv"))
                return [], [], file_errors
            if cells is None:
                break
            if fieldnames is None:
                normalized = [_normalize_header(c) for c in cells]
                if {"nr", "namn_efternamn"} <= set(normalized):
                    file_errors.extend(
                        (detail, f"row {start_line}: dubblettkolumn") for detail in _duplicate_headers(cells)
                    )
                    try:
                        layout = _detect_layout(normalized)
                    except ValueError as e:
                        file_errors.append((str(e), f"row {start_line}: ogiltig-adresslayout"))
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
                code = e.code if isinstance(e, _RowError) else "ogiltig-rad"
                errors.append((f"row {reader.line_num}: {e}", f"row {start_line}: {code}"))
    if fieldnames is None:
        file_errors.append(
            ("hittade ingen rubrikrad (med kolumnerna 'Nr' och 'Namn Efternamn') i filen", "rubrikrad-saknas")
        )
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
        raise _RowError("namn-saknas", "kolumnen 'Namn Efternamn' saknas eller är tom")

    nr_raw = row.get("nr", "")
    if nr_raw == "":
        raise _RowError("nr-saknas", "kolumnen 'Nr' saknas eller är tom")
    try:
        nr = int(nr_raw)
    except ValueError as exc:
        raise _RowError("ogiltigt-nr", f"ogiltigt Nr: {nr_raw!r}") from exc
    if not 0 <= nr <= 999_999:  # member numbers have four digits; a huge one would exhaust the 32-bit counter
        raise _RowError("ogiltigt-nr", f"ogiltigt Nr: {nr_raw!r}")

    if layout == SPLIT_LAYOUT:
        try:
            postal_code = normalize_postal_code(row.get("postnummer") or None)
        except ValueError as exc:
            raise _RowError("ogiltigt-postnummer", f"ogiltigt postnummer: {row.get('postnummer')!r}") from exc
        city = row.get("postort") or None
        postal_raw, needs_review = None, False
    else:
        postal_raw = row.get("postadress") or None
        postal_code, city = split_postal_address(postal_raw)
        needs_review = city is not None and postal_code is None
    if city is not None and len(city) > 100:
        # After BOTH branches — a non-parsing legacy Postadress lands whole in city.
        raise _RowError("postort-for-lang", "Postort får vara högst 100 tecken")

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
                _save_membership_fields(membership, changed)
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


def _save_membership_fields(membership, changed: dict) -> None:
    """UPDATE only the membership columns the caller changed.

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
    _save_membership_fields(membership, changed)


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
    """Create the main person. A friexemplar keeps its e-mail for contact only."""
    person = Member.create(
        membership=membership,
        role="huvudmedlem",
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        phone=row["phone"],
    )
    if membership.membership_status != Status.FRIEXEMPLAR:
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


def _flag_genebank_ids(prefix: str) -> list[int]:
    return [gb.id for gb in Genebank.select(Genebank.id, Genebank.name) if gb.name[:1].upper() == prefix]


def _link_flag_herds(nr: int, group: list[dict], membership, dry_run: bool, report: dict) -> None:
    """G/M flags link herd G<Nr>/M<Nr> with link_herd, which compares the herd's contact with the register (#117).
    A missing or ambiguous herd is a warning, never a row skip."""
    for key, prefix in (("g", "G"), ("m", "M")):
        if not any(row[key] for row in group):
            continue
        code = f"{prefix}{nr}"
        genebanks = _flag_genebank_ids(prefix)
        matches = (
            list(Herd.select().where(Herd.herd == code, Herd.genebank.in_(genebanks))) if len(genebanks) == 1 else []
        )
        if len(matches) != 1:  # the flag's genebank must be one, and the herd in it one
            reason = "not found" if len(genebanks) == 1 else f"flag {prefix} names {len(genebanks)} genebanks"
            report["herd_warnings"].append(f"herd {code} {reason} — flag ignored")
            continue
        herd = matches[0]
        if herd.membership_id is not None:
            if membership is not None and herd.membership_id == membership.id:
                continue  # already linked (re-import)
            report["herd_warnings"].append(f"herd {code} already linked to membership {herd.membership_id}")
            continue
        if dry_run or membership is None:
            report["herd_links"] += 1
            continue
        cases = link_herd(herd.id, membership.id, herd_code=code, genebank_id=herd.genebank_id)
        if cases is None:  # linked, renumbered or moved since the lookup
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
    """Summary counts shared by all import modes."""
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


BILLING_PROPOSAL_HEADER = (
    "membership_id",
    "member_number",
    *(f"current_{field}" for field in BILLING_FIELDS),
    *(f"proposed_{field}" for field in BILLING_FIELDS),
    "anteckning",
    "beslut",
    *(f"exporterat_{field}" for field in BILLING_FIELDS),
    "underlag",
)


def _require_matrikel_actor(actor_user_id: int | str | None) -> User:
    if actor_user_id is None:
        raise click.UsageError("--apply kräver --actor-user-id <id> (auditloggens aktör)")
    try:
        actor_user_id = int(actor_user_id)
    except ValueError:
        raise click.UsageError("--actor-user-id måste vara ett heltal") from None
    actor = User.get_or_none(User.id == actor_user_id)
    if actor is None or not actor.is_active or not (actor.is_admin or actor.is_matrikel_admin):
        raise click.UsageError("--actor-user-id måste vara ett aktivt konto med rollen admin eller matrikel_admin")
    return actor


def _validated_billing(values: dict) -> dict:
    from blueprints.common import EMAIL_RE  # Load blueprints after CLI registration.

    fields = parse_billing_fields(values)
    if fields.get("billing_email") and not EMAIL_RE.fullmatch(fields["billing_email"]):
        raise ValueError("Ogiltig e-post för faktura")
    if any("\0" in value for value in fields.values() if value):
        raise ValueError("Ogiltigt textfält")
    return fields


def _billing_source(ms: Membership) -> dict:
    return {
        "membership_id": ms.id,
        "member_number": ms.member_number,
        "anteckning": ms.notes,
        **{f"current_{key}": getattr(ms, key) for key in BILLING_FIELDS},
    }


def _proposal_proof(source: dict, exported: dict) -> str:
    return hashlib.sha256(json.dumps([source, exported], sort_keys=True).encode()).hexdigest()


def _memberships_with_current_persons():
    return _active_main_members().select(Member.membership)


def _export_billing_proposals(path: str) -> None:
    rows = []
    with_notes = 0
    query = Membership.select().where(Membership.notes != "", Membership.id.in_(_memberships_with_current_persons()))
    for ms in query.order_by(Membership.id).iterator():
        if not ms.notes.strip():
            continue
        with_notes += 1
        # The full note must fit in a CSV field when the reviewed file is read back.
        if len(ms.notes) > 100_000:
            continue
        proposal = parse_billing_note(ms.notes)
        if proposal is None:
            continue
        fields, _ = proposal
        try:
            fields = _validated_billing(fields)
        except ValueError:
            continue
        if all(value == getattr(ms, key) for key, value in fields.items()):
            continue
        source = _billing_source(ms)
        exported = {key: fields.get(key, getattr(ms, key)) for key in BILLING_FIELDS}
        rows.append(
            {
                **source,
                **{f"proposed_{k}": v for k, v in exported.items()},
                **{f"exporterat_{k}": v for k, v in exported.items()},
                "underlag": _proposal_proof(source, {k: proposal_cell(v) for k, v in exported.items()}),
            }
        )

    try:
        write_proposals(path, BILLING_PROPOSAL_HEADER, rows)
    except FileExistsError:
        raise click.ClickException("Förslagsfilen finns redan") from None
    except OSError:
        raise click.ClickException("Förslagsfilen kunde inte skapas") from None
    click.echo(f"Med anteckning: {with_notes}, med förslag: {len(rows)}, utan förslag: {with_notes - len(rows)}")


def _apply_billing_row(row: dict, actor: User) -> str:
    if row["beslut"] == "hoppa över":
        return "hoppa över (beslut)"
    try:
        membership_id = int(row["membership_id"])
    except ValueError:
        return "ogiltiga värden"
    with DB_PROXY.atomic():
        try:
            ms = _locked_membership(membership_id)
        except Membership.DoesNotExist:
            return "underlaget har ändrats"
        source = _billing_source(ms)
        exported = {key: row[f"exporterat_{key}"] for key in BILLING_FIELDS}
        if (
            _proposal_proof(source, exported) != row["underlag"]
            or any(row[k] != proposal_cell(v) for k, v in source.items())
            or not _memberships_with_current_persons().where(Member.membership == ms).exists()
        ):
            return "underlaget har ändrats"
        proposed = {key: row[f"proposed_{key}"] for key in BILLING_FIELDS}
        if row["beslut"] == "godkänn" and proposed != exported:
            return "ändrad rad utan beslutet ändra"
        try:
            desired = _validated_billing(proposed)
        except ValueError:
            return "ogiltiga värden"
        changed = {key: v for key, v in desired.items() if v != getattr(ms, key)}
        if not changed:
            return "oförändrade"
        before = {key: getattr(ms, key) for key in changed}
        _save_membership_fields(ms, changed)
        write_matrikel_audit(actor, "membership_updated", ms, {"before": before, "after": changed})
    return "Skrivna"


@members_cli.command("billing-proposals")
@click.option("--out", metavar="FIL", help="Skapa en ny förslagsfil för granskning.")
@click.option("--apply", "apply_file", metavar="FIL", help="Verkställ godkända och ändrade rader i förslagsfilen.")
@click.option("--actor-user-id", metavar="ID", help="Aktiv admin eller matrikel_admin (krävs med --apply).")
def billing_proposals_cmd(out: str | None, apply_file: str | None, actor_user_id: str | None) -> None:
    """Föreslå fakturaadresser ur anteckningarna eller verkställ en granskad fil.

    Ange godkänn, ändra eller hoppa över i kolumnen beslut. Tomt beslut hoppar
    över raden. Välj ändra om du rättar något i kolumnerna proposed_*.
    """
    if (out is None) == (apply_file is None):
        raise click.UsageError("Ange antingen --out FIL eller --apply FIL")
    counts = {
        "Skrivna": 0,
        "hoppa över (beslut)": 0,
        "underlaget har ändrats": 0,
        "ändrad rad utan beslutet ändra": 0,
        "ogiltiga värden": 0,
        "oförändrade": 0,
    }
    try:
        if out is not None:
            _export_billing_proposals(out)
            return
        actor = _require_matrikel_actor(actor_user_id)
        try:
            rows = read_decisions(apply_file, BILLING_PROPOSAL_HEADER, raw_cells=True)
        except (OSError, UnicodeError, csv.Error):
            raise click.ClickException("Förslagsfilen kunde inte läsas") from None
        except ValueError as err:
            raise click.ClickException(str(err)) from None
        for row in rows:
            counts[_apply_billing_row(row, actor)] += 1
    except DatabaseError:
        # PostgreSQL diagnostics can include the row or the rejected value.
        if apply_file is not None:
            click.echo(f"Skrivna: {counts['Skrivna']}", err=True)
        raise click.ClickException("Databasfel vid hantering av fakturaförslag") from None
    click.echo(", ".join(f"{reason}: {count}" for reason, count in counts.items()))


_apply_option = click.option(
    "--apply", "apply_links", is_flag=True, help="Write the links (default prints the plan only)."
)
_actor_option = click.option(
    "--actor-user-id",
    type=int,
    default=None,
    help="Admin/matrikel_admin user recorded as audit actor (required with --apply).",
)
_plan_option = click.option("--plan", "plan_value", help="Kontrollvärde från planen du läst (required with --apply).")
_PLAN_CHANGED = "planen har ändrats sedan du läste den — läs den nya planen ovan och kör om med dess värde"


def _link_actor(apply_links, actor_user_id, plan_value):
    if not apply_links:
        return None
    if actor_user_id is None:
        raise click.UsageError("--apply kräver --actor-user-id <id> (auditloggens aktör)")
    if plan_value is None:
        raise click.UsageError("--apply kräver --plan <kontrollvärde> från planen du har läst")
    return _require_matrikel_actor(actor_user_id)


def _plan_checksum(lines) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()[:16]


@members_cli.command("link-by-herd")
@_apply_option
@_actor_option
@_plan_option
def link_by_herd_cmd(apply_links: bool, actor_user_id: int | None, plan_value: str | None) -> None:
    """Link accounts to the main member of the membership whose herd they own.

    The sole owner of herd G<Nr>/M<Nr> (tied to membership Nr) is proposed if
    the main member's name matches, or if either account e-mail matches the
    member's address in full or by a non-generic local part of at least five characters.
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
    actor = _link_actor(apply_links, actor_user_id, plan_value)
    to_link, listed, already = _plan_herd_links()
    lines = {id(pair): _pair_line(*pair) for pair in to_link}
    value = _plan_checksum(lines.values())
    if apply_links and plan_value != value:
        _echo_plan("Att koppla", [lines[id(p)] for p in to_link], listed, already)
        click.echo(f"Kontrollvärde: {value}")
        raise click.ClickException(_PLAN_CHANGED)

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


def _pair_line(main, user, codes, reason) -> str:
    return f"{'/'.join(codes)}: {_pair_detail(main, user)} | skäl: {reason}"


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


_GENERIC_LOCAL_PARTS = frozenset(
    """
    admin administrator bibliotek biblioteket bokning contact e-post ekonomi epost expedition expeditionen
    faktura fakturor foreningen föreningen garden gården hej hello info info- kaniner kansli kansliet kassan
    kassor kassör klubben kontakt kontakta kontakten kontoret mail medlem medlemmar museet museum no-reply
    noreply office order ordforande ordförande post posten postmaster reception receptionen sekretariat
    sekretariatet sekreterare styrelse styrelsen support webmaster
    gotlandskanin gotlandskaninen mellerudskanin mellerudskaninen
    """.split()
)


def _norm_email(address: str | None) -> str:
    address = (address or "").strip().lower()
    return address if re.fullmatch(r"[^@\s]+@[^@\s]+", address) else ""


def _match_reason(person: Member, user: User) -> str | None:
    name = _norm_name(user.fullname)
    if name and name == _norm_name(f"{person.first_name} {person.last_name}"):
        return "namn lika"
    # the association's own address for the person, which Google sign-in also links by
    workspace = _norm_email(person.workspace_email)
    if workspace.endswith(WORKSPACE_DOMAIN) and workspace == _norm_email(user.google_email):
        return "Workspace-adress lika (Google)"

    address = _norm_email(person.email)
    if not address:
        return None
    account_addresses = (("Google", _norm_email(user.google_email)), ("kontots e-post", _norm_email(user.email)))
    for source, email in account_addresses:
        if email == address:
            return f"e-post lika ({source})"
    local = address.partition("@")[0]
    if len(local) >= 5 and local not in _GENERIC_LOCAL_PARTS:
        for source, email in account_addresses:
            if email.partition("@")[0] == local:
                return f"lokaldel lika ({source})"
    return None


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


def _owner_index(users=None) -> tuple[dict[int, dict[int, User]], set[int]]:
    """Herd id -> {user id: user} with role owner, and the users with an incomplete owner role."""
    owners: dict[int, dict[int, User]] = {}
    incomplete: set[int] = set()
    if users is None:
        users = User.select().order_by(User.id)
    for user in users:
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
    """Decide every link first: returns (to_link [(main, user, codes, reason)], listed [(codes, reason)], already)."""
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
    pairs: dict[tuple[int, int], list] = {}  # (main id, user id) -> [main, user, codes, reason]
    possible: set[tuple[int, int]] = set()  # every matching owner: a counterpart, linked only through pairs
    # Counterparts are counted in one place and before anything is filtered or sorted out: for every herd row
    # that has an owner, whatever its code, genebank or state, every person left in the membership the row is
    # stored on, and in the one its code's number names, who matches an owner.
    for herd in Herd.select():
        herd_owners = owners.get(herd.id)
        if not herd_owners:
            continue
        # One number, whatever stands around it ("M901 " too); a leading zero names no membership.
        number = re.fullmatch(r"[^0-9]*([1-9][0-9]*)[^0-9]*", herd.herd or "")
        named = memberships.get(int(number.group(1))) if number else None
        behind = {herd.membership_id, getattr(named, "id", None)} - {None}
        for person in Member.select().where(Member.membership.in_(behind), Member.end_date.is_null(True)):
            possible |= {(person.id, uid) for uid, user in herd_owners.items() if _match_reason(person, user)}
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
    for key, (main, user, codes, reason) in pairs.items():
        if len(by_main[key[0]]) > 1 or len(by_user[key[1]]) > 1:
            listed.append((codes, f"flera möjliga kopplingar ({_pair_detail(main, user)})"))
        elif link_access_delta(main, user):
            listed.append((codes, "länken skulle ge kontot åtkomst till fler besättningar"))
        else:
            to_link.append((main, user, codes, reason))
    return to_link, listed, len(already)


def _check_owner(code, main, user, incomplete, listed, already, pairs) -> None:
    """One herd with one owner account and one active main member: already done, listed or a candidate pair."""
    if main.user_id == user.id:
        already.add((main.id, user.id))
    elif user.id in incomplete:
        listed.append(([code], "kontots ägarroll är ofullständig"))
    elif not user.is_active:
        listed.append(([code], "kontot är inaktivt"))
    elif (reason := _match_reason(main, user)) is None:
        listed.append(([code], "namnet skiljer sig mellan kontot och huvudmedlemmen"))
    elif reason == "namn lika" and (
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
        pairs.setdefault((main.id, user.id), [main, user, [], reason])[2].append(code)


def _owner_membership_detail(owner_ids, membership_by_user, membership_id, incomplete) -> tuple[str, bool]:
    details = []
    needs_review = False
    for user_id in owner_ids:
        linked_id = membership_by_user.get(user_id)
        if linked_id is None:
            relation = "ägaren är inte kopplad till matrikeln"
        elif linked_id == membership_id:
            relation = "ägaren hör till medlemskapet"
        else:
            relation = "ägaren hör till ett annat medlemskap"
            needs_review = True
        if user_id in incomplete:
            relation += ", kontots ägarroll är ofullständig"
            needs_review = True
        details.append(f"konto {user_id}: {relation}")
    return ", ".join(details) or "ingen ägare", needs_review


def _active_main_members():
    return Member.select(Member.id, Member.membership, Member.user, Member.first_name, Member.last_name).where(
        Member.role == "huvudmedlem", Member.end_date.is_null(True)
    )


def _plan_same_number_links() -> tuple[list, list[str]]:
    banks = {prefix: _flag_genebank_ids(prefix) for prefix in "GM"}
    owners, incomplete = _owner_index()
    membership_by_user = dict(
        Member.select(Member.user, Member.membership)
        .where(Member.user.is_null(False), Member.end_date.is_null())
        .tuples()
    )
    mains = {main.membership_id: main for main in _active_main_members()}
    memberships = {
        m.member_number: m
        for m in Membership.select(Membership.id, Membership.member_number, Membership.membership_status).where(
            Membership.member_number.is_null(False)
        )
    }
    to_link, listed = [], []
    herds = Herd.select(Herd, Genebank).join(Genebank).where(Herd.membership.is_null()).order_by(Herd.herd, Herd.id)
    for herd in herds:
        code = herd.herd
        if not re.fullmatch(r"[GM][1-9][0-9]*", code):
            continue
        prefix, number = code[0], int(code[1:])
        status = "inaktiv" if herd.is_active is False else "aktiv"
        detail = f"{code} (id {herd.id}), genbank {_q(herd.genebank.name)}, {status}"
        membership = memberships.get(number)
        if len(banks[prefix]) != 1:
            listed.append(f"{detail} | {prefix} motsvarar {len(banks[prefix])} genbanker")
        elif herd.genebank_id != banks[prefix][0]:
            listed.append(f"{detail} | fel genbank för prefixet")
        elif membership is None:
            listed.append(f"{detail} | medlemskap nr {number} saknas")
        else:
            detail += f" -> medlemskap nr {number} (id {membership.id}, {membership.membership_status})"
            main = mains.get(membership.id)
            if main is None:
                end_dates = [person.end_date for person in membership.persons.select(Member.end_date)]
                reason = (
                    "medlemskapet är avslutat" if end_dates and all(end_dates) else "medlemskapet saknar huvudmedlem"
                )
                listed.append(f"{detail} | {reason}")
                continue
            relation, needs_review = _owner_membership_detail(
                owners.get(herd.id, ()), membership_by_user, membership.id, incomplete
            )
            name = _q(f"{main.first_name} {main.last_name}".strip())
            account = f"konto {main.user_id}" if main.user_id else "inget konto"
            line = f"{detail} | huvudmedlem {main.id}: {name} ({account}) | {relation}"
            if needs_review:
                listed.append(line)
            else:
                to_link.append((herd, membership, (main.id, main.user_id), line))
    return to_link, listed


def _apply_same_number_link(herd, membership, main, actor) -> str | None:
    """Return the reason if the herd could no longer be linked as planned."""
    with DB_PROXY.atomic():
        current = _locked_membership_by_number(membership.member_number)
        if current is None or current.id != membership.id:
            return "medlemsnumret hör inte längre till medlemskapet"
        if current.membership_status != membership.membership_status:
            return "medlemskapets status har ändrats"
        main_id, user_id = main  # the account that gets access is part of the plan
        account = Member.user == user_id if user_id else Member.user.is_null(True)
        if not _active_main_members().where(Member.membership == current, Member.id == main_id, account).exists():
            return "huvudmedlemmen eller huvudmedlemmens konto har ändrats"
        try:
            cases = link_herd(herd.id, membership.id, herd_code=herd.herd, genebank_id=herd.genebank_id)
        except Herd.DoesNotExist:
            return "besättningen finns inte längre"
        if cases is None:
            current_herd = Herd.get_by_id(herd.id)  # still locked by link_herd
            if current_herd.membership_id is not None:
                return "besättningen är redan kopplad"
            if current_herd.herd != herd.herd:
                return "besättningens kod har ändrats"
            return "besättningens genbank har ändrats"
        write_matrikel_audit(
            actor,
            "herd_membership_linked",
            membership,
            {"herd_id": herd.id, "main_member_id": main_id, "source": "cli"},
        )
    return None


@members_cli.command("link-same-number")
@_apply_option
@_actor_option
@_plan_option
def link_same_number_cmd(apply_links: bool, actor_user_id: int | None, plan_value: str | None) -> None:
    """Link unassigned G/M herds to the membership with the same number.

    Read the plan first: each link gives the household access to the herd.
    """
    actor = _link_actor(apply_links, actor_user_id, plan_value)
    candidates, listed = _plan_same_number_links()
    lines = [
        f"Att koppla: {len(candidates)}",
        *(f"  {line}" for _, _, _, line in candidates),
        f"Till granskning: {len(listed)}",
        *(f"  {line}" for line in listed),
    ]
    value = _plan_checksum(lines)
    click.echo("\n".join(lines))
    click.echo(f"Kontrollvärde: {value}")
    if not apply_links:
        click.echo("(endast plan — kör om med --apply --actor-user-id <id> --plan <kontrollvärde>)")
        return
    if plan_value != value:
        raise click.ClickException(_PLAN_CHANGED)

    skipped = []
    for herd, membership, main, _ in candidates:
        reason = _apply_same_number_link(herd, membership, main, actor)
        if reason:
            skipped.append(f"  {herd.herd} (id {herd.id}): {reason}")
    click.echo(f"Kopplade: {len(candidates) - len(skipped)}, Överhoppade: {len(skipped)}")
    for line in skipped:
        click.echo(line)


_WORKSPACE_COLUMNS = {
    "first name": "ws_fornamn",
    "last name": "ws_efternamn",
    "email address": "workspace_email",
    "status": "ws_status",
    "last sign in": "ws_senast_inloggad",
    "org unit path": "ws_org_enhet",
    "recovery email": "recovery_email",
}
WORKSPACE_PROPOSAL_HEADER = (
    "workspace_email",
    "ws_fornamn",
    "ws_efternamn",
    "ws_status",
    "ws_senast_inloggad",
    "ws_org_enhet",
    "utfall",
    "skal",
    "kandidater",
    "proposed_member_number",
    "proposed_person_id",
    "roll",
    "person_namn",
    "person_workspace_email",
    "konto_id",
    "konto_atgard",
    "besattningar",
    "beslut",
    "exporterat_member_number",
    "exporterat_person_id",
    "exporterat_konto_id",
    "exporterat_besattning_ids",
    "underlag",
)
_WS_STALE = "underlaget har ändrats"
_WS_OTHER_HERDS = "konto ej kopplat: ger besättningar, koppla i matrikeln"


def _read_workspace_csv(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, strict=True)
            header = [re.sub(r"\s*\[[^\[\]]*\]$", "", h.strip()).strip().casefold() for h in next(reader, [])]
            for required in ("first name", "last name", "email address"):
                if required not in header:
                    raise click.ClickException(required)
            if any(header.count(name) > 1 for name in _WORKSPACE_COLUMNS):
                raise click.ClickException("Tvetydig rubrikrad i Workspace-filen")
            columns = {key: header.index(name) for name, key in _WORKSPACE_COLUMNS.items() if name in header}
            rows = []
            for cells in reader:
                if len(cells) != len(header):
                    raise click.ClickException("Workspace-filen kunde inte läsas")
                rows.append({key: cells[index] for key, index in columns.items()})
            return rows
    except (OSError, csv.Error, UnicodeError):
        raise click.ClickException("Workspace-filen kunde inte läsas") from None


def _workspace_users(email):
    # Google sign-in records this verified address. User.email is self-editable.
    return (
        User.select(User.id, User.google_email, User.is_active, User._privileges)
        .where(fn.LOWER(User.google_email) == email)
        .order_by(User.id)
    )


def _workspace_person_reasons(person, name, email, recovery, user):
    reasons = []
    if email and (person.workspace_email or "").lower() == email:
        reasons.append("redan satt")
    if user and person.user_id == user.id:
        reasons.append("kontot med samma Google-adress är kopplat till personen")
    if name and name == _norm_name(f"{person.first_name} {person.last_name}"):
        reasons.append("namn lika")
    contact = _norm_email(person.email)
    if recovery and recovery == contact:
        reasons.append("återställningsadressen är matrikelns e-post")
    local = email.partition("@")[0]
    if email and email == contact:
        reasons.append("e-post lika")
    elif len(local) >= 5 and local not in _GENERIC_LOCAL_PARTS and local == contact.partition("@")[0]:
        reasons.append("lokaldel lika")
    return reasons


@dataclass
class _WorkspaceMatch:
    ws: dict
    user: User | None
    holder_id: int | None
    herds: list
    address_holder_id: int | None = None
    people: dict = field(default_factory=dict)  # person -> signals
    memberships: dict = field(default_factory=dict)  # membership -> ownership signals without a single person
    historical: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)


def _workspace_account_conflict(person, user, email):
    if user is None and (person.workspace_email or "").lower() == email:
        return False  # Already set, with no account for this Google address.
    return person.user_id is not None and person.user_id != getattr(user, "id", None)


def _workspace_owned_herds(owners):
    by_user = defaultdict(list)
    for herd in (
        Herd.select(
            Herd.id, Herd.herd, Herd.membership, Membership.id, Membership.member_number, Membership.membership_status
        )
        .join(Membership)
        .where(Herd.id.in_(list(owners)))
        .order_by(Herd.id)
    ):
        for uid in owners[herd.id]:
            by_user[uid].append(herd)
    return by_user


def _workspace_match(ws, people, mains, herds, incomplete):
    email = _norm_email(ws["workspace_email"])
    recovery = _norm_email(ws.get("recovery_email"))
    name = _norm_name(f"{ws['ws_fornamn']} {ws['ws_efternamn']}")
    users = list(_workspace_users(email)) if email and "\0" not in email else []
    user = users[0] if len(users) == 1 else None
    holder_id = next((p.id for p in people if user and p.user_id == user.id), None)
    match = _WorkspaceMatch(ws, user, holder_id, herds[user.id] if user else [])
    if not email.endswith(WORKSPACE_DOMAIN) or "\0" in email:
        match.problems.append("inte föreningens domän")
    elif len(email) > 255:
        match.problems.append("ogiltig Workspace-adress")
    if len(users) > 1:
        match.problems.append("flera konton har Google-adressen")
    for p in people:
        if email and (p.workspace_email or "").lower() == email:
            match.address_holder_id = p.id
        if is_anonymized(p):
            continue
        reasons = _workspace_person_reasons(p, name, email, recovery, user)
        if reasons:
            if p.end_date is None and p.membership_id in mains:
                match.people[p] = reasons
            else:
                match.historical.setdefault(p.membership.member_number, []).extend(reasons)

    for herd in match.herds:
        ms = herd.membership
        reason = f"kontot äger besättning {herd.herd} i medlemskap nr {ms.member_number or '–'}"
        same_membership = [p for p in match.people if p.membership_id == ms.id]
        if len(same_membership) == 1:
            match.people[same_membership[0]].append(reason)
        elif ms.id in mains or match.people:
            match.memberships.setdefault(ms, []).append(reason)
        else:
            match.historical.setdefault(ms.member_number, []).append(reason)

    if match.people or match.memberships:
        needs_link = user and holder_id is None
        if needs_link and not user.is_active:
            match.problems.append("kontot är inaktivt")
        if needs_link and user.id in incomplete:
            match.problems.append("kontot har en ofullständig ägarroll")
        if holder_id and (not match.people or any(holder_id != p.id for p in match.people)):
            match.problems.append("kontot är kopplat till en annan person")
        if any(_workspace_account_conflict(p, user, email) for p in match.people):
            match.problems.append("personen är kopplad till ett annat konto")
        if any(p.workspace_email and p.workspace_email.lower() != email for p in match.people):
            match.problems.append("personen har redan en annan workspace_email")
        if match.address_holder_id and all(p.id != match.address_holder_id for p in match.people):
            match.problems.append("adressen är satt på en annan person")
    return match


def _workspace_proof(row, person, user, holder_id, membership, herds, address_holder_id):
    # Hash private source state and the exact spreadsheet-escaped cells the reviewer sees.
    mutable = {"beslut", "proposed_member_number", "proposed_person_id", "roll", "underlag"}
    snapshot = {key: row.get(key, "") for key in WORKSPACE_PROPOSAL_HEADER if key not in mutable}
    source = {
        "person": None
        if person is None
        else [
            person.id,
            person.membership_id,
            person.membership.member_number,
            person.first_name,
            person.last_name,
            person.role,
            person.end_date.isoformat() if person.end_date else None,
            person.email,
            person.workspace_email,
            person.user_id,
            person.membership.membership_status,
        ],
        "konto": None if user is None else [user.id, user.google_email, user.is_active, holder_id],
        # This also makes a redirected or new person stale on replay, without needing a separate run log.
        "adressinnehavare": address_holder_id,
        # A reviewed membership number can change hands even on a row without a proposed person.
        "medlemskap": membership.id if membership and membership.member_number else None,
        "ägarskap": [(h.id, h.herd, h.membership_id, h.membership.member_number) for h in herds],
    }
    return _proposal_proof(source, snapshot)


def _workspace_herd_cells(delta):
    ordered = sorted(delta, key=lambda h: (h["herd"], h["id"]))
    return {
        "besattningar": ", ".join(h["herd"] for h in ordered),
        "exporterat_besattning_ids": ",".join(str(h["id"]) for h in ordered),
    }


def _workspace_proposal(match, address_counts, person_counts):
    ws, user = match.ws, match.user
    email = _norm_email(ws["workspace_email"])
    people = match.people
    person = next(iter(people)) if len(people) == 1 else None
    memberships = {p.membership for p in people} | match.memberships.keys()
    ms = next(iter(memberships)) if len(memberships) == 1 else None
    problems = list(match.problems)
    if address_counts[ws["workspace_email"].strip().lower()] > 1:
        problems.append("adressen förekommer flera gånger i CSV-filen")
    if any(person_counts[p] > 1 for p in people):
        problems.append("flera Workspace-rader pekar på samma person")
    if len(people) > 1:
        problems.append("flera personer matchar")
    if match.memberships:
        problems.append("medlemskapskandidat utan person")
    for membership in memberships:
        if membership.membership_status != Status.ACTIVE:
            problems.append(f"medlemskapet har status {membership.membership_status}")
    already_set = person and email and (person.workspace_email or "").lower() == email
    linked = person and user and person.user_id == user.id
    if already_set and user and not linked:
        problems.append("adressen är redan satt men kontot är inte kopplat")
    if problems:
        outcome = "granska"
    elif person:
        outcome = "redan klar" if already_set else "förslag"
    else:
        outcome = "ingen träff"

    reasons, candidates = [], []
    for p, signals in people.items():
        reasons.extend(signals)
        candidates.append(
            f"person {p.id} i nr {p.membership.member_number or '–'} {_q(f'{p.first_name} {p.last_name}')} "
            f"({', '.join(signals)})"
        )
    for membership, signals in match.memberships.items():
        reasons.extend(signals)
        candidates.append(f"medlemskap nr {membership.member_number or '–'} ({', '.join(signals)})")
    if not memberships:
        for number in sorted(match.historical, key=lambda nr: nr or 0):
            reasons.extend(match.historical[number])
            reasons.append(f"bara i avslutat medlemskap nr {number or '–'}")
    delta = []
    action = ""
    if linked:
        action = "redan kopplat"
    elif user and outcome == "förslag":
        action = "koppla"
        delta = link_access_delta(person, user)

    row = {
        **{k: v for k, v in ws.items() if k != "recovery_email"},
        "utfall": outcome,
        "skal": " | ".join(dict.fromkeys(reasons + problems)),
        "kandidater": " | ".join(candidates) if outcome == "granska" else "",
        "proposed_member_number": ms.member_number if ms else None,
        "proposed_person_id": person.id if person else None,
        "roll": person.role if person else ("familjemedlem" if ms and not people else ""),
        "person_namn": f"{person.first_name} {person.last_name}".strip() if person else "",
        "person_workspace_email": person.workspace_email if person else "",
        "konto_id": user.id if user else None,
        "konto_atgard": action,
        **_workspace_herd_cells(delta),
    }
    row["exporterat_member_number"] = row["proposed_member_number"]
    row["exporterat_person_id"] = row["proposed_person_id"]
    row["exporterat_konto_id"] = row["konto_id"]
    row["underlag"] = _workspace_proof(
        {k: proposal_cell(v) for k, v in row.items()},
        person,
        user,
        match.holder_id,
        ms,
        match.herds,
        match.address_holder_id,
    )
    return row


def _export_workspace_proposals(csv_path, out):
    accounts = _read_workspace_csv(csv_path)
    people = list(
        Member.select(
            Member.id,
            Member.first_name,
            Member.last_name,
            Member.email,
            Member.workspace_email,
            Member.user,
            Member.role,
            Member.end_date,
            Member.membership,
            Membership.id,
            Membership.member_number,
            Membership.membership_status,
        )
        .join(Membership)
        .order_by(Member.id)
    )
    mains = {p.membership_id for p in people if p.role == "huvudmedlem" and p.end_date is None and not is_anonymized(p)}
    owners, incomplete = _owner_index(User.select(User.id, User._privileges))
    herds = _workspace_owned_herds(owners)
    matches = [_workspace_match(ws, people, mains, herds, incomplete) for ws in accounts]
    address_counts = Counter(ws["workspace_email"].strip().lower() for ws in accounts)
    person_counts = Counter(p for match in matches for p in match.people)
    rows = [_workspace_proposal(match, address_counts, person_counts) for match in matches]
    try:
        write_proposals(out, WORKSPACE_PROPOSAL_HEADER, rows)
    except FileExistsError:
        raise click.ClickException("Förslagsfilen finns redan") from None
    except OSError:
        raise click.ClickException("Förslagsfilen kunde inte skapas") from None
    counts = Counter(row["utfall"] for row in rows)
    click.echo(
        ", ".join(f"{outcome}: {counts[outcome]}" for outcome in ("förslag", "redan klar", "granska", "ingen träff"))
    )


def _workspace_id(value):
    # These columns address PostgreSQL integer keys. Never send free text from the sheet to the DB.
    if value.isascii() and value.isdecimal() and len(value) <= 10 and 0 < int(value) <= 2**31 - 1:
        return int(value)
    return None


def _lock_workspace_targets(original_id, target_id, numbers, email):
    ids = {pid for pid in (original_id, target_id) if pid is not None}
    # An edit can move the target to a different household. Lock BOTH roots, in id order,
    # before the Google account and both person rows, including for the original source proof.
    roots = Membership.id.in_(Member.select(Member.membership).where(Member.id.in_(ids)))
    roots |= Membership.member_number.in_([nr for nr in numbers if nr is not None])
    memberships = {ms.id: ms for ms in Membership.select().where(roots).order_by(Membership.id).for_update()}
    users = list(_workspace_users(email).for_update()) if email and "\0" not in email else []
    people = {p.id: p for p in Member.select().where(Member.id.in_(ids)).order_by(Member.id).for_update()}
    return memberships, users, people


def _write_workspace_row(row, actor):
    approved = row["beslut"] == "godkänn"
    email = _norm_email(row["workspace_email"].removeprefix(" "))
    original_id = _workspace_id(row["exporterat_person_id"])
    target_id = _workspace_id(row["proposed_person_id"])
    original_number = _workspace_id(row["exporterat_member_number"])
    number = _workspace_id(row["proposed_member_number"])
    memberships, users, people = _lock_workspace_targets(original_id, target_id, (original_number, number), email)
    if len(users) > 1:
        return _WS_STALE
    user = next(iter(users), None)
    holder_id = Member.select(Member.id).where(Member.user == user).scalar() if user else None
    owners, incomplete = _owner_index(users)
    herds = _workspace_owned_herds(owners)[user.id] if owners else []
    numbered = {ms.member_number: ms for ms in memberships.values() if ms.member_number}
    address_holder_id = (
        Member.select(Member.id).where(fn.LOWER(Member.workspace_email) == email).scalar()
        if email and "\0" not in email
        else None
    )
    proof = _workspace_proof(
        row, people.get(original_id), user, holder_id, numbered.get(original_number), herds, address_holder_id
    )
    if proof != row["underlag"]:
        return _WS_STALE
    if approved:
        if any(row[f"proposed_{key}"] != row[f"exporterat_{key}"] for key in ("member_number", "person_id")):
            return "ändrad rad utan beslutet ändra"
        if row["utfall"] not in ("förslag", "redan klar"):
            return "kräver beslutet ändra"

    if not email.endswith(WORKSPACE_DOMAIN) or "\0" in email or len(email) > 255:
        return "ogiltig Workspace-adress"
    new = row["proposed_person_id"] == "ny" and not approved
    person = people.get(target_id)
    if new:
        membership = numbered.get(number)
    else:
        membership = memberships.get(person.membership_id) if person else None
    if (
        not membership
        or (row["proposed_member_number"] and number is None)
        or membership.member_number != number
        or membership.membership_status != Status.ACTIVE
        or not any(not is_anonymized(main) for main in _active_main_members().where(Member.membership == membership))
        or (person and (person.end_date is not None or is_anonymized(person)))
    ):
        return _WS_STALE if approved else "ogiltigt mål"

    if person and person.workspace_email and person.workspace_email.lower() != email:
        return _WS_STALE if approved else "personen har redan en annan workspace_email"
    if address_holder_id is not None and address_holder_id != target_id:
        return _WS_STALE if approved else "adressen är satt på en annan person"
    if holder_id is not None and holder_id != target_id:
        return "Kontot är redan kopplat"
    if person and _workspace_account_conflict(person, user, email):
        return "Personen har redan ett konto"
    link = user is not None and holder_id is None
    if link:
        if not user.is_active:
            return "Kontot är inaktivt"
        if user.id in incomplete:
            return "kontot har en ofullständig ägarroll"

    if new:
        first, last = (row[key].removeprefix(" ") for key in ("ws_fornamn", "ws_efternamn"))
        if any("\0" in s or len(s) > 100 for s in (first, last)) or (first, last) == (
            ANONYMIZED_FIRST_NAME,
            ANONYMIZED_LAST_NAME,
        ):
            return "ogiltigt namn"
        person = add_person(membership, {"first_name": first, "last_name": last, "role": "familjemedlem"}, actor)
    delta = link_access_delta(person, user) if link else []
    if approved and any(row[key] != proposal_cell(value) for key, value in _workspace_herd_cells(delta).items()):
        # link_member_user checks gains; also reject the disappearance of ALL previously reviewed gains.
        return _WS_STALE
    before = person.workspace_email
    changed = (before or "").lower() != email
    if changed:
        person.workspace_email = email
        person.save(only=[Member.workspace_email, Member.updated_at])
        write_matrikel_audit(
            actor,
            "person_updated",
            membership,
            {"person_id": person.id, "before": {"workspace_email": before}, "after": {"workspace_email": email}},
        )
    if link:
        if delta and not approved:
            return _WS_OTHER_HERDS
        confirmed = {int(i) for i in row["exporterat_besattning_ids"].split(",")} if delta else None
        link_member_user(
            person.id,
            user.id,
            actor=actor,
            mode="admin" if confirmed else "cli",
            confirmed_herd_ids=confirmed,
        )
    return "Skrivna" if changed or link else "redan klar"


def _apply_workspace_row(row, actor):
    if row["beslut"] == "hoppa över":
        return "hoppa över (beslut)"
    try:
        with DB_PROXY.atomic():
            return _write_workspace_row(row, actor)
    except ConfirmRequired:
        return _WS_STALE
    except LinkError as err:
        return err.title
    except IntegrityError as err:
        diag = getattr(getattr(err, "orig", None), "diag", None)
        if getattr(diag, "constraint_name", None) == "idx_member_workspace_email_unique":
            return "adressen är satt på en annan person"
        raise


@members_cli.command("workspace-proposals")
@click.argument("csv_path", required=False, metavar="[CSV]")
@click.option("--out", metavar="FIL", help="Skapa en ny förslagsfil från Google-exporten.")
@click.option("--apply", "apply_file", metavar="FIL", help="Verkställ besluten i den granskade förslagsfilen.")
@click.option("--actor-user-id", metavar="ID", help="Aktiv admin eller matrikel_admin (krävs med --apply).")
def workspace_proposals_cmd(csv_path, out, apply_file, actor_user_id):
    """Matcha Workspace-konton mot matrikeln eller verkställ en granskad fil.

    Lämna beslut tomt för att hoppa över raden. Välj ändra för att ange ett
    annat medlemsnummer och person-id, eller ny för att lägga till en familjemedlem.
    """
    if (out is None) == (apply_file is None) or (out is None) != (csv_path is None):
        raise click.UsageError("Ange CSV --out FIL eller --apply FIL --actor-user-id ID")
    counts = Counter({"Skrivna": 0})
    # This one-shot CLI reports via click. Even DEBUG SQL logs contain bound addresses and audit payloads.
    previous_level = logging.root.manager.disable
    logging.disable(max(logging.CRITICAL, previous_level))
    try:
        if out is not None:
            _export_workspace_proposals(csv_path, out)
            return
        actor = _require_matrikel_actor(actor_user_id)
        try:
            rows = read_decisions(apply_file, WORKSPACE_PROPOSAL_HEADER, raw_cells=True)
        except (OSError, UnicodeError, csv.Error):
            raise click.ClickException("Förslagsfilen kunde inte läsas") from None
        except ValueError as err:
            raise click.ClickException(str(err)) from None
        for row in rows:
            counts[_apply_workspace_row(row, actor)] += 1
    except DatabaseError:
        if apply_file is not None:
            click.echo(", ".join(f"{outcome}: {count}" for outcome, count in counts.items()), err=True)
        raise click.ClickException("Databasfel vid hantering av Workspace-förslag") from None
    finally:
        logging.disable(previous_level)
    click.echo(", ".join(f"{outcome}: {count}" for outcome, count in counts.items()))
