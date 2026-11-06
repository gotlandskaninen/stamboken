"""
Flask CLI for member registry operations.

Usage:
    flask members import <csv_path> [--dry-run]
    flask members link-users [--apply]

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

`link-users` is the manual follow-up to that last rule: it links existing
herdbook accounts to imported person rows on the CONTACT email, so
User.effective_herd_ids() and /medlem/profil work for them. It is a
dry run unless --apply is given, never overwrites an existing
Member.user, never touches workspace_email and never calls the auto-link
helper (which matches workspace_email only — imported rows have none).
Because the spreadsheet email is unverified, a link may never convey herd
access the account does not already hold: candidates whose link_access_delta
is non-empty are parked for manual review, where the matrikel-admin UI is
the only path that can confirm them. --apply writes through
link_member_user() and therefore requires --actor-user-id.
"""

import csv
import logging
import re

import click
from flask.cli import AppGroup
from peewee import IntegrityError, fn
from utils.database import DB_PROXY, Herd, Member, Membership, User
from utils.matrikel import (
    ANONYMIZED_FIRST_NAME,
    ANONYMIZED_LAST_NAME,
    ConfirmRequired,
    LinkError,
    link_access_delta,
    link_member_user,
    normalize_postal_code,
    raise_counter_to,
    split_postal_address,
)

logger = logging.getLogger(__name__)

members_cli = AppGroup("members", help="Member registry operations.")


@members_cli.command("import")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Print the full import plan without writing.")
def import_cmd(csv_path: str, dry_run: bool) -> None:
    """Import memberships from a MATR2026 CSV file."""
    rows, errors, file_errors = _read_rows(csv_path)
    if file_errors:
        # The whole file is unusable (no header row, duplicate columns, an
        # address layout we cannot read). Abort here — before _group_rows and
        # before the counter is raised — so a rejected file leaves nothing
        # behind, not even a moved member-number high-water mark.
        for line in file_errors:
            click.echo(f"Error: {line}", err=True)
        raise click.ClickException("filen avvisades — inga rader importerade")
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

    _print_report(report, dry_run)

    # Non-zero exit code when any rows errored — lets CI detect bad imports.
    if report["errors"]:
        for line in report["errors"]:
            click.echo(f"Error: {line}", err=True)
        raise click.ClickException(f"{len(report['errors'])} row(s) failed to import — see stderr for details")


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
            Membership.membership_status == "active",
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
                membership = Membership.create(member_number=nr, membership_status="active", **fields)
                Member.create(
                    membership=membership,
                    role="huvudmedlem",
                    first_name=main["first_name"],
                    last_name=main["last_name"],
                    email=main["email"],
                    phone=main["phone"],
                )
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
        Member.create(
            membership=membership,
            role="huvudmedlem",
            first_name=main["first_name"],
            last_name=main["last_name"],
            email=main["email"],
            phone=main["phone"],
        )


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
    """G/M flags link herd G<Nr>/M<Nr>. A missing herd is a warning, never a row skip."""
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
        report["herd_links"] += 1
        if not dry_run and membership is not None:
            herd.membership = membership
            herd.save()


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
        membership = Membership.create(
            member_number=None,
            membership_status="friexemplar",
            address=row["address"],
            postal_code=row["postal_code"],
            city=row["city"],
            payment_note=row["payment_note"],
            notes=notes,
        )
        Member.create(
            membership=membership,
            role="huvudmedlem",
            first_name=row["first_name"],
            last_name=row["last_name"],
            email=row["email"],
            phone=row["phone"],
        )


def _leftover_numberless(adopted_ids: set[int]) -> list[tuple[int, str]]:
    """Active number-less memberships left after import — manual reconciliation list."""
    leftovers = []
    query = (
        Membership.select()
        .where(
            Membership.member_number.is_null(True),
            Membership.membership_status == "active",
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

    click.echo(
        f"Memberships created: {report['memberships_created']}, "
        f"Persons created: {report['persons_created']}, "
        f"Friexemplar created: {report['friexemplar_created']}, "
        f"Merges: {len(report['merges'])}, "
        f"Matched existing (skipped): {report['matched_existing']}, "
        f"Manual review: {len(report['review'])}, "
        f"Herd links: {report['herd_links']}, "
        f"Errors: {len(report['errors'])}"
    )
    if dry_run:
        click.echo("(dry-run — no writes performed)")


@members_cli.command("link-users")
@click.option("--apply", "apply_links", is_flag=True, help="Write the links (default prints the plan only).")
@click.option(
    "--actor-user-id",
    type=int,
    default=None,
    help="Admin/matrikel_admin user recorded as audit actor (required with --apply).",
)
def link_users_cmd(apply_links: bool, actor_user_id: int | None) -> None:
    """Link existing herdbook users to member rows on the contact email.

    The contact email is UNVERIFIED (spreadsheet), so a match may never
    convey herd access the account does not already hold: candidates whose
    link would convey herds (link_access_delta) are parked for manual review
    — the matrikel-admin UI is the path that can confirm them.

    --apply commits ONE TRANSACTION PER CANDIDATE (link_member_user's own),
    not one for the run: a crashed run keeps the links it already made and a
    re-run simply continues from there.
    """
    actor = None
    if apply_links:
        if actor_user_id is None:
            raise click.UsageError("--apply kräver --actor-user-id <id> (auditloggens aktör)")
        actor = User.get_or_none(User.id == actor_user_id)
        if actor is None or not actor.is_active or not (actor.is_admin or actor.is_matrikel_admin):
            raise click.UsageError(
                f"--actor-user-id {actor_user_id}: måste vara ett aktivt konto med rollen admin eller matrikel_admin"
            )

    report = _plan_user_links()

    if apply_links and report["linked"]:
        applied, raced, parked = [], [], []
        # NO outer transaction for the run — a deliberate deviation:
        # link_member_user() opens its own
        # DB_PROXY.atomic() and each candidate therefore commits on its own.
        # A batch under one outer transaction would hold every membership →
        # user → person row lock it took until the last candidate committed
        # (RELEASE SAVEPOINT retains the locks a savepoint acquired), blocking
        # every concurrent admin action on those rows for the length of the run
        # and risking a deadlock against a writer taking them in between.
        # Per candidate is safe because each link is audited on its own and the
        # command is idempotent: a crashed run leaves the links it already made
        # in place, and a re-run re-plans (linked rows drop out) and continues.
        for member, user in report["linked"]:
            # No pre-locks — the operation owns them. A refused or raced
            # candidate rolls back only its own transaction and never blocks a
            # later one: the unique-index backstop surfaces as
            # the mapped LinkError or as a raw IntegrityError, both -> raced.
            # Invalidation: mode="cli" can never convey — a
            # non-empty delta raises ConfirmRequired before any write — so the
            # operation's post-commit _invalidate_genebanks() always sees an
            # empty set here and nothing is ever invalidated by this command.
            try:
                link_member_user(member.id, user.id, actor=actor, mode="cli")
            except ConfirmRequired as needs:
                parked.append((member, user, [h["herd"] for h in needs.conveys]))
            except (LinkError, IntegrityError):
                raced.append((member, user))
            else:
                applied.append((member, user))
        report["linked"] = applied
        report["raced"] = raced
        report["needs_review"].extend(parked)

    _print_link_report(report, apply_links)


def _plan_user_links() -> dict:
    """Match unlinked active person rows to users by contact email.

    Candidates are grouped by lowercased email, so a user (matched on that
    same lowercased email) can never appear in more than one group — which
    is what guarantees at most one member row per user.
    """
    report = {
        "linked": [],  # (member, user)
        "ambiguous": [],  # (email, reason, [member, ...])
        "already_linked": [],  # (member, user, existing member)
        "needs_review": [],  # (member, user, herd codes) — link would grant new herd access
        "raced": [],  # (member, user) — plan invalidated by a concurrent write during --apply
        "unmatched": 0,
    }
    groups: dict[str, list] = {}
    candidates = (
        Member.select()
        .where(
            Member.end_date.is_null(True),
            Member.user.is_null(True),
            Member.email.is_null(False),
        )
        .order_by(Member.id)
    )
    for member in candidates:
        groups.setdefault(member.email.strip().lower(), []).append(member)

    for email, members in sorted(groups.items()):
        users = list(User.select().where(fn.LOWER(User.email) == email).order_by(User.id))
        if not users:
            report["unmatched"] += len(members)
        elif len(users) > 1:
            labels = ", ".join(_user_label(u) for u in users)
            report["ambiguous"].append((email, f"{len(users)} users share this email ({labels})", members))
        elif len(members) > 1:
            reason = f"user {_user_label(users[0])} matches {len(members)} member rows"
            report["ambiguous"].append((email, reason, members))
        else:
            # An existing link (active OR ended person row) is never
            # overwritten — one user, at most one member row.
            existing = Member.select().where(Member.user == users[0]).first()
            if existing is not None:
                report["already_linked"].append((members[0], users[0], existing))
                continue
            # Escalation guard: the unverified spreadsheet email must never
            # convey herd access the account does not already hold. The plan
            # uses the same delta the operation re-computes under its locks
            # (link_access_delta) — a non-empty delta is parked for the
            # matrikel-admin UI, the only path that can confirm it.
            delta = link_access_delta(members[0], users[0])
            if delta:
                report["needs_review"].append((members[0], users[0], [h["herd"] for h in delta]))
            else:
                report["linked"].append((members[0], users[0]))
    return report


def _user_label(user) -> str:
    return user.username or user.email


def _member_label(member) -> str:
    name = f"{member.first_name} {member.last_name}".strip()
    return f"member {member.id}: {name} <{member.email}>"


def _print_link_report(report: dict, apply_links: bool) -> None:
    if not apply_links:
        click.echo("DRY-RUN — planned user links (re-run with --apply to write):")

    if report["linked"]:
        click.echo("Linked:" if apply_links else "Would link:")
        for member, user in report["linked"]:
            click.echo(f"  {_member_label(member)} -> user {_user_label(user)}")

    if report["ambiguous"]:
        click.echo("Ambiguous (nothing linked — needs manual resolution):")
        for email, reason, members in report["ambiguous"]:
            click.echo(f"  {email}: {reason}")
            for member in members:
                click.echo(f"    {_member_label(member)}")

    if report["already_linked"]:
        click.echo("Already linked (skipped — an existing link is never overwritten):")
        for member, user, existing in report["already_linked"]:
            click.echo(f"  {_member_label(member)} — user {_user_label(user)} already linked to member {existing.id}")

    if report["needs_review"]:
        click.echo(
            "Needs manual review (the link would convey herd access the account "
            "does not have — confirm it in the matrikel UI):"
        )
        for member, user, herd_codes in report["needs_review"]:
            click.echo(f"  {_member_label(member)} — user {_user_label(user)}, herds {'/'.join(herd_codes)}")

    if report["raced"]:
        click.echo("Skipped (changed since the plan was made — re-run to re-check):")
        for member, user in report["raced"]:
            click.echo(f"  {_member_label(member)} — user {_user_label(user)}")

    ambiguous_rows = sum(len(members) for _, _, members in report["ambiguous"])
    click.echo(
        f"Linked: {len(report['linked'])}, "
        f"Ambiguous: {len(report['ambiguous'])} ({ambiguous_rows} member rows), "
        f"Already linked: {len(report['already_linked'])}, "
        f"Needs review: {len(report['needs_review'])}, "
        f"Unmatched candidates: {report['unmatched']}"
    )
    if not apply_links:
        click.echo("(dry-run — no writes performed; re-run with --apply)")
