"""The herd's contact as it is shown: the herd's own values, or values from the member register (#117).

The herd's columns name, email, mobile_phone and physical_address hold only its own values; NULL or "" means
the row is fetched from the contact person (name, e-mail, mobile) or the membership (address). Every reader
and writer of these rows goes through this module.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from utils.database import (
    DB_PROXY,
    HERD_CONTACT_COLUMNS,
    PRIVACY_LEVELS,
    Herd,
    HerdAccessGrant,
    Member,
    Membership,
    User,
)

CONTACT_FIELDS = ("name", "email", "mobile_phone", "physical_address")
# the flat keys of a general PATCH that only `contact` may change on a compared herd
CONTACT_KEYS = frozenset((*CONTACT_FIELDS, *(f"{f}_privacy" for f in CONTACT_FIELDS)))
Source = Literal["egen", "person", "medlemskap"]
Mode = Literal["ej_jamford", "person", "fritext", "ingen"]

STALE = "Kontaktuppgifterna har ändrats sedan sidan öppnades. Ladda om sidan och försök igen."
LEGACY_REFUSED = "Kontaktuppgifterna ändras i nya Stamboken. Har du inte tillgång där, kontakta genbanksansvarig."
# the old app's empty address: its herd form joins an absent (hidden) or null street as text
LEGACY_EMPTY_ADDRESSES = ("||", "undefined||", "null||")


class ContactConflict(Exception):
    """The form showed another state than the one under the lock: 409 contact-changed."""


class ContactForbidden(Exception):
    """The user may not make this change of the contact: 403 contact-forbidden."""


@dataclass(frozen=True)
class Row:
    value: str | None
    source: Source
    pending: bool
    alternative: str | None  # the register's value when the row is own and differs


@dataclass(frozen=True)
class HerdContact:
    mode: Mode
    contact_member_id: int | None  # the contact person, only while active on an active membership
    rows: dict[str, Row]  # keys = CONTACT_FIELDS


def herd_contacts(herds: Sequence[Herd], *, any_status: bool = False) -> dict[int, HerdContact]:
    """The contact of each herd, by herd id, with one query for all of them. `any_status`: as if the membership
    were active, for the lifecycle, so that a paused membership also compares the values it would show."""
    compared = [h for h in herds if h.membership_id is not None and h.contact_pending is not None]
    persons = {}  # membership id -> {person id: person}: active persons, of active memberships unless any_status
    if compared:
        where = [Member.membership.in_({h.membership_id for h in compared}), Member.end_date.is_null(True)]
        if not any_status:
            where.append(Membership.membership_status == "active")
        query = (
            Member.select(
                Member.id,
                Member.membership,
                Member.first_name,
                Member.last_name,
                Member.email,
                Member.phone,
                Member.role,
                Membership.id,
                Membership.address,
                Membership.postal_code,
                Membership.city,
            )
            .join(Membership)
            .where(*where)
        )
        for person in query:
            persons.setdefault(person.membership_id, {})[person.id] = person
    contacts = {h.id: _uncompared(h) for h in herds}
    contacts.update({h.id: _compared(h, persons.get(h.membership_id, {})) for h in compared})
    return contacts


def herd_contact(herd: Herd) -> HerdContact:
    return herd_contacts([herd])[herd.id]


def _uncompared(herd):
    """Not compared with the register: every row is the herd's column, untouched, as today."""
    return HerdContact("ej_jamford", None, {f: Row(getattr(herd, f), "egen", False, None) for f in CONTACT_FIELDS})


def _compared(herd, persons):
    person = persons.get(herd.contact_member_id)
    mode = "person" if person else "fritext" if herd.name else "ingen"
    # the address is the household's: fetched while the membership has an active person, whoever the contact is
    membership = next(iter(persons.values())).membership if persons else None
    parts = (membership.address, membership.postal_code, membership.city) if membership else ()
    # in fritext, "Använd medlemskapets" makes the main member the contact: her name is the name's alternative
    main = next((p for p in persons.values() if p.role == "huvudmedlem"), None) if mode == "fritext" else None
    named = person or main
    fetched = {
        "name": f"{named.first_name} {named.last_name}" if named else None,
        "email": (person.email or None) if person else None,
        "mobile_phone": (person.phone or None) if person else None,
        "physical_address": "|".join(p or "" for p in parts) if any(parts) else None,
    }
    rows = {}
    for field in CONTACT_FIELDS:
        own = getattr(herd, field)
        # a contact outside the register has no person to fetch e-mail and mobile from: those rows are own
        if own or (mode == "fritext" and field in ("email", "mobile_phone")):
            other = fetched[field]
            alternative = other if other and normalize(field, own) != normalize(field, other) else None
            rows[field] = Row(own or None, "egen", field in herd.contact_pending, alternative)
        else:
            rows[field] = Row(fetched[field], "medlemskap" if field == "physical_address" else "person", False, None)
    return HerdContact(mode, person.id if person else None, rows)


def matrikel_reader_herd_ids(user: User | None, herds: Sequence[Herd]) -> set[int]:
    """Decision 11: of `herds`, those the user reads the register's values for: admin, the genebank's manager,
    and active persons on the herd's active membership (main and family members, caretakers with an active
    grant on the herd). Not the old owner role. At most two queries, however many herds."""
    if user is None:
        return set()
    if user.is_admin:
        return {h.id for h in herds}
    found = {h.id for h in herds if h.genebank_id in (user.is_manager or [])}
    linked = [h for h in herds if h.membership_id is not None and h.id not in found]
    if not linked:
        return found
    persons = list(
        Member.select(Member.id, Member.membership, Member.role)
        .join(Membership)
        .where(
            Member.user == user.id,
            Member.membership.in_({h.membership_id for h in linked}),
            Member.end_date.is_null(True),
            Membership.membership_status == "active",
        )
    )
    household = {p.membership_id for p in persons if p.role in ("huvudmedlem", "familjemedlem")}
    found |= {h.id for h in linked if h.membership_id in household}
    caretakers = {p.id: p.membership_id for p in persons if p.role == "skotare"}
    pending = {h.id: h.membership_id for h in linked if h.id not in found}
    if caretakers and pending:
        grants = HerdAccessGrant.select(HerdAccessGrant.herd, HerdAccessGrant.member).where(
            HerdAccessGrant.member.in_(list(caretakers)),
            HerdAccessGrant.herd.in_(list(pending)),
            HerdAccessGrant.revoked_at.is_null(True),
            HerdAccessGrant.valid_until.is_null(True) | (HerdAccessGrant.valid_until >= date.today()),
        )
        # a grant counts only on the caretaker's own membership's herd
        found |= {g.herd_id for g in grants if caretakers[g.member_id] == pending[g.herd_id]}
    return found


def is_matrikel_reader(user: User | None, herd: Herd) -> bool:
    return herd.id in matrikel_reader_herd_ids(user, [herd])


def active_persons(herd: Herd, *, any_status: bool = False) -> list[Member]:
    """The active persons on the herd's active membership, main member first. `any_status`: of a membership in any
    status, as herd_contacts."""
    if herd.membership_id is None:
        return []
    where = [Member.membership == herd.membership_id, Member.end_date.is_null(True)]
    if not any_status:
        where.append(Membership.membership_status == "active")
    return list(
        Member.select(Member.id, Member.user, Member.first_name, Member.last_name, Member.role)
        .join(Membership)
        .where(*where)
        .order_by(Member.role != "huvudmedlem", Member.id)
    )


def _person_json(person) -> dict:
    return {"id": person.id, "name": f"{person.first_name} {person.last_name}", "role": person.role}


def may_choose_contact(user: User, herd: Herd, persons: Sequence[Member]) -> bool:
    """Spec, Beslut om personerna: admin, the genebank's manager and the active main member on the herd's active
    membership (`persons` = active_persons(herd)) choose the contact person."""
    return bool(
        user.is_admin
        or herd.genebank_id in (user.is_manager or [])
        or any(p.user_id == user.id and p.role == "huvudmedlem" for p in persons)
    )


def contact_field(user: User, herd: Herd, contact: HerdContact, *, reader: bool, private_access: bool) -> dict | None:
    """The `contact` object of a herd response: whole for a matrikel reader, a smaller one for others with
    private access (no mode, person, fetched values or their privacy), none for anyone else."""
    privacy = {f: getattr(herd, f"{f}_privacy") or "private" for f in CONTACT_FIELDS}  # NULL counts as private
    if not reader:
        if not private_access:
            return None
        rows = {
            f: {"source": "egen", "value": r.value, "privacy": privacy[f]}
            if r.source == "egen"
            else {"source": "hamtad"}
            for f, r in contact.rows.items()
        }
        return {"rows": rows}
    persons = active_persons(herd)
    chooses = may_choose_contact(user, herd, persons)
    current = next((p for p in persons if p.id == contact.contact_member_id), None)
    data = {
        "mode": contact.mode,
        "contact_member": _person_json(current) if current else None,
        "rows": {
            f: {"source": r.source, "privacy": privacy[f], "pending": r.pending, "alternative": r.alternative}
            for f, r in contact.rows.items()
        },
    }
    if not chooses and contact.mode == "fritext":
        data["rows"]["name"]["alternative"] = None  # the main member's name: not for those who cannot choose
    if chooses:
        data["persons"] = [_person_json(p) for p in persons]
    return data


def normalize(field: str, value: str | None) -> object:
    """The value as it is compared with the register (spec: Överflyttning). None and "" are the same.
    A match the normalisation cannot settle compares as different."""
    if not value or not value.strip():
        return None
    if field == "email":
        return "".join(value.split()).lower()
    if field in ("mobile_phone", "wire_phone"):
        # only separators that cannot change the number; "/" and "." may start an extension
        compact = re.sub(r"[\s()\-‐-―−]", "", value)
        if not re.fullmatch(r"\+?[0-9]+", compact):
            return value.strip()  # text in the number ("ank 78"): not settled, so only the exact text is equal
        # only a marked country code (+46, 0046) is Swedish; an unmarked leading 46 stays and compares as different
        return re.sub(r"^(\+|00)46", "0", compact)
    if field == "physical_address":
        # street, postal code, city; a value without "|" is a street only
        street, postal_code, city = (value.split("|", 2) + ["", ""])[:3]
        compact = "".join(postal_code.split())
        # "623 00" is 62300; anything else in the part (", lgh A") is kept, so it compares as different
        postal_code = compact if re.fullmatch(r"[0-9]{5}", compact) else " ".join(postal_code.lower().split())
        parts = (" ".join(street.lower().split()), postal_code, " ".join(city.lower().split()))
        return parts if any(parts) else None
    if field == "name":
        return frozenset(value.lower().split())
    if field in ("www", "location"):  # not in the register: compared with an echo or what a form showed
        return value.strip()
    raise ValueError(f"no normalisation for {field}")


def lock_herd(herd_id: int) -> Herd:
    """Lock the herd's membership and then the herd (SELECT ... FOR UPDATE), the order of soft_delete_person and
    _relock_me, and return the herd as it is under the locks. Call it inside a transaction."""
    membership_id = Herd.select(Herd.membership).where(Herd.id == herd_id).get().membership_id
    if membership_id is not None:
        Membership.select(Membership.id).where(Membership.id == membership_id).for_update().get()
    herd = Herd.select().where(Herd.id == herd_id).for_update().get()
    if herd.membership_id != membership_id:  # linked in between: its membership is not the one locked
        raise ContactConflict(STALE)
    return herd


def compare_with_register(herd: Herd) -> tuple[dict, dict[str, str]]:
    """Spec, Överflyttning: the first comparison of a linked herd's contact with the register. `herd` needs only
    its id, membership, contact columns and their privacy, so the migration can pass a row with those alone.

    Returns the columns to write and the case per row: "lika", "olika", "bara_besattningen", "bara_matrikeln" or
    "bada_tomma", and for the name "person" or "fritext" when the name is filled in."""
    # a paused membership too: its persons are compared, and its rows show once it is active again
    persons = active_persons(herd, any_status=True)
    main = next((p for p in persons if p.role == "huvudmedlem"), None)
    name = herd.name if normalize("name", herd.name) else None
    same = [p for p in persons if normalize("name", f"{p.first_name} {p.last_name}") == normalize("name", name)]
    # step 1, the contact person: the main member for an empty name, the one person the name is, else fritext
    if name is None:
        contact, cases = main, {"name": "bara_matrikeln" if main else "bada_tomma"}
    elif len(same) == 1:
        contact, name, cases = same[0], None, {"name": "person"}
    else:
        contact, cases = None, {"name": "fritext"}
    # step 2: each row against what the read gives afterwards, without the herd's own values
    contact_id = contact.id if contact is not None else None
    probe = Herd(id=herd.id, membership=herd.membership_id, contact_member=contact_id, name=name, contact_pending=[])
    fetched = herd_contacts([probe], any_status=True)[probe.id].rows
    for field in CONTACT_FIELDS[1:]:
        own, register = normalize(field, getattr(herd, field)), normalize(field, fetched[field].value)
        if own is None:
            cases[field] = "bada_tomma" if register is None else "bara_matrikeln"
        elif register is None:
            cases[field] = "bara_besattningen"
        else:
            cases[field] = "lika" if own == register else "olika"
    changes = {"contact_pending": [f for f in CONTACT_FIELDS if cases[f] in ("fritext", "olika")]}
    if contact_id is not None:
        changes["contact_member"] = contact_id
    for field in CONTACT_FIELDS:
        if cases[field] not in ("fritext", "olika", "bara_besattningen") and getattr(herd, field):
            changes[field] = None  # a copy of the register's value, or blank
        # decision 4: a row that was empty starts hidden, so a value added later is not shown before anyone chose
        privacy = f"{field}_privacy"
        if cases[field] in ("bara_matrikeln", "bada_tomma") and (getattr(herd, privacy) or "private") != "private":
            changes[privacy] = "private"
    return changes, cases


def link_herd(herd_id: int, membership_id: int, herd_code: str | None = None) -> dict[str, str]:
    """Spec, Livscykel: the one function that sets Herd.membership. Links a herd without membership and compares
    its contact with the register (compare_with_register); returns the case per row. A herd already linked, to
    this membership or another, is left as it is: {} (a move is #153). So is one whose code is no longer
    `herd_code`, the G/M code the caller found it by (renumbered meanwhile). Locks the membership and then the
    herd, re-reads the herd under the locks and writes only the columns that change."""
    with DB_PROXY.atomic():
        Membership.select(Membership.id).where(Membership.id == membership_id).for_update().get()
        herd = Herd.select().where(Herd.id == herd_id).for_update().get()
        if herd.membership_id is not None or herd_code not in (None, herd.herd):
            return {}
        herd.membership = membership_id
        changes, cases = compare_with_register(herd)
        Herd.update(membership=membership_id, **changes).where(Herd.id == herd_id).execute()
    return cases


def _keeps_choice(field: str, before: str | None, after: str | None, contact_changed: bool) -> bool:
    """Decision 14: a row keeps its privacy while it shows the same value. After a change of contact person, by
    any path and to fritext too, an empty name, e-mail or mobile does not: its choice would pass on to the next
    contact's first value."""
    value = normalize(field, after)
    empty = value is None and field != "physical_address"
    return value == normalize(field, before) and not (contact_changed and empty)


def _household_herds(membership_id: int) -> list[Herd]:
    """The membership's herds, locked after the membership. FOR NO KEY UPDATE, as anonymize_ended_persons holds
    them: no key column changes."""
    return list(Herd.select().where(Herd.membership == membership_id).order_by(Herd.id).for_update("FOR NO KEY UPDATE"))


def _clear(herd: Herd, fields) -> None:
    """Empty the herd's own rows `fields`: they start hidden and wait for no answer."""
    changes = {**dict.fromkeys(fields), **{f"{f}_privacy": "private" for f in fields}}
    if herd.contact_pending is not None:
        changes["contact_pending"] = [f for f in herd.contact_pending if f not in fields]
    Herd.update(**changes).where(Herd.id == herd.id).execute()


def snapshot_before_leaving(member: Member) -> dict[int, HerdContact]:
    """Spec, Livscykel: the contact of the household's herds before `member` leaves, for on_person_leaving. Call it
    under the membership's lock, before the end date or the erasure. It locks the herds."""
    return herd_contacts(_household_herds(member.membership_id), any_status=True)


def on_person_anonymizing(member: Member) -> None:
    """Spec, Livscykel: before `member` is erased, the household's herds lose own rows equal to her e-mail or phone,
    the fixed phone too, unless another person on the membership has the same value (an erased one has none)."""
    sources = {"email": "email", "mobile_phone": "phone", "wire_phone": "phone"}
    others = list(
        Member.select(Member.email, Member.phone).where(
            Member.membership == member.membership_id, Member.id != member.id
        )
    )
    for herd in _household_herds(member.membership_id):
        gone = []
        for field, attr in sources.items():
            value = normalize(field, getattr(herd, field))
            if value is not None and value == normalize(field, getattr(member, attr)):
                if all(normalize(field, getattr(o, attr)) != value for o in others):
                    gone.append(field)
        if gone:
            _clear(herd, gone)


def on_person_leaving(member: Member, before: dict[int, HerdContact]) -> None:
    """Spec, Livscykel, after `member`'s end date or erasure, and decision 10: a herd whose contact person is not
    active any more gets the active main member, or none. As after any change of contact, a fetched row that shows
    another value than `before` starts hidden (decision 14). The herd's own rows stay: they may be the farm's."""
    persons = list(
        Member.select(Member.id, Member.role).where(
            Member.membership == member.membership_id, Member.end_date.is_null(True)
        )
    )
    main = next((p.id for p in persons if p.role == "huvudmedlem"), None)
    herds = _household_herds(member.membership_id)
    moved = {}
    for herd in herds:
        if herd.contact_member_id is not None and herd.contact_member_id not in {p.id for p in persons}:
            herd.contact_member = moved[herd.id] = main
    after = herd_contacts(herds, any_status=True)
    for herd in herds:
        changes = {"contact_member": moved[herd.id]} if herd.id in moved else {}
        for field, row in after[herd.id].rows.items():
            same = _keeps_choice(field, before[herd.id].rows[field].value, row.value, herd.id in moved)
            privacy = f"{field}_privacy"
            if row.source != "egen" and not same and (getattr(herd, privacy) or "private") != "private":
                changes[privacy] = "private"
        if changes:
            Herd.update(**changes).where(Herd.id == herd.id).execute()


def on_household_erased(membership_id: int) -> None:
    """Spec, Livscykel: every person on the membership is erased. All the herds' own contact rows go, the fixed
    phone and the website too, and start hidden."""
    for herd in _household_herds(membership_id):
        _clear(herd, HERD_CONTACT_COLUMNS)


def check_flat_fields(herd: Herd, fields, contact) -> None:
    """On a compared herd the contact rows and their privacy change only through `contact`, and never both ways
    in one call: ValueError (400)."""
    flat = sorted(CONTACT_KEYS & set(fields))
    if flat and (herd.contact_pending is not None or contact is not None):
        raise ValueError(f"Kontaktuppgifterna ändras med fältet contact, inte med {', '.join(flat)}.")


PLACE_FIELDS = ("wire_phone", "www", "location")


def check_place_shown(herd: Herd, fields, shown, *, with_privacy=True) -> None:
    """Spec, Skrivningar, "Varje ändring gäller det som formuläret visade", for the fixed phone, website and place: a
    call that sends one of them or its privacy also sends what the form showed of it, {"value", "privacy"} in
    `shown` (place_shown), and `herd` is under lock_herd. `with_privacy=False` is the admin form, which shows no
    privacy: there it is compared only when sent. Missing or malformed: ValueError (400); another row than the
    stored one: ContactConflict."""
    for field in PLACE_FIELDS:
        if field not in fields and f"{field}_privacy" not in fields:
            continue
        seen = shown.get(field) if isinstance(shown, dict) else None
        if (
            not isinstance(seen, dict)
            or "value" not in seen
            or not isinstance(seen["value"], (str, type(None)))
            or (with_privacy and "privacy" not in seen)
            or seen.get("privacy") not in (None, *PRIVACY_LEVELS)
        ):
            raise ValueError(f"place_shown.{field} krävs: värdet och synligheten som formuläret visade.")
        stored_privacy = getattr(herd, f"{field}_privacy") or "private"
        if normalize(field, seen["value"]) != normalize(field, getattr(herd, field)) or (
            "privacy" in seen and (seen["privacy"] or "private") != stored_privacy
        ):
            raise ContactConflict(STALE)


def _rank(level):
    """public < authenticated < private; NULL, and an unknown stored value, counts as private."""
    return PRIVACY_LEVELS.index(level) if level in PRIVACY_LEVELS else len(PRIVACY_LEVELS) - 1


def legacy_contact_form(herd: Herd, form: dict, user: User) -> dict:
    """Spec, Skrivningar, Gamla appen (decision 15): the old app sends back the whole herd it read, also fields
    hidden from the reader, and on a herd linked to a membership it changes no contact field. Each one sent must
    be an echo of this user's read (`herd` under lock_herd), so a hidden one only empty, whatever the register
    holds: the answer never tells whether a guess was right. Else ValueError, and the call saves nothing.

    Returns the form to save: without the contact fields, and without a privacy wider than the stored one."""
    if herd.membership_id is None:
        return form
    shown = herd.filtered_dict(user, with_contact=False)
    for field in (f for f in HERD_CONTACT_COLUMNS if f in form):
        sent = form[field]
        # an exact echo stands as it is: a marker can also be stored, saved before the link
        if field == "physical_address" and sent in LEGACY_EMPTY_ADDRESSES and sent != shown.get(field):
            sent = None
        if not isinstance(sent, (str, type(None))) or normalize(field, sent) != normalize(field, shown.get(field)):
            raise ValueError(LEGACY_REFUSED)
    privacy = {f"{f}_privacy" for f in HERD_CONTACT_COLUMNS}
    return {
        key: value
        for key, value in form.items()
        if key not in HERD_CONTACT_COLUMNS and (key not in privacy or _rank(value) >= _rank(getattr(herd, key)))
    }


def _given(value):
    """A value the form filled in; blank counts as none."""
    return value if isinstance(value, str) and value.strip() else None


def _parse(patch) -> dict:
    """The rows of a well-formed patch, or ValueError (400)."""
    if not isinstance(patch, dict):
        raise ValueError("contact måste vara ett objekt.")
    rows = patch.get("rows", {})
    if not isinstance(rows, dict) or not set(rows) <= set(CONTACT_FIELDS):
        raise ValueError(f"contact.rows tar bara {', '.join(CONTACT_FIELDS)}.")
    member = patch.get("contact_member")
    if (
        (member is not None and (isinstance(member, bool) or not isinstance(member, int)))
        or not isinstance(patch.get("name"), (str, type(None)))
        or not isinstance(patch.get("shown", {}), dict)
        or (member is not None and _given(patch.get("name")))  # a person contact has no name of its own
    ):
        raise ValueError("contact: contact_member är ett id eller null, name en text eller null, shown ett objekt.")
    for field, row in rows.items():
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("shown"), dict)
            or row.get("source") not in ("egen", "medlemskap")
            or not isinstance(row.get("value"), (str, type(None)))
            or row.get("privacy") not in (None, *PRIVACY_LEVELS)
            or row.get("answer") not in (None, "behall", "anvand")
            or (row.get("answer") is not None and (row["answer"] == "anvand") != (row["source"] == "medlemskap"))
            or (row.get("answer") == "behall" and "value" in row and not _given(row["value"]))  # keep, not empty
        ):
            raise ValueError(f"contact.rows.{field}: source, value, privacy, answer eller shown är fel.")
    return rows


def apply_contact_patch(herd_id: int, patch: dict, user: User) -> None:
    """Apply the `contact` object of a PATCH (spec: Skrivningar) in the caller's transaction, so that a refusal
    rolls back the whole call. Under the locks it decides, in this order: the permission (403, before any value
    is compared, so that a refusal never tells whether a guess was right), the state the form showed (409), the
    chosen person (400). It writes only the columns that change.

    A row the patch leaves out is unchanged."""
    rows = _parse(patch)
    with DB_PROXY.atomic():
        herd = lock_herd(herd_id)
        current = herd_contact(herd)
        compared = herd.contact_pending is not None
        persons = active_persons(herd)
        reader = is_matrikel_reader(user, herd)
        chooses = may_choose_contact(user, herd, persons)
        own_name = _given(current.rows["name"].value) if current.rows["name"].source == "egen" else None
        top = "contact_member" in patch or "name" in patch
        target = (
            (patch.get("contact_member"), _given(patch.get("name"))) if top else (current.contact_member_id, own_name)
        )
        name_row = rows.get("name")
        if (
            reader
            and name_row
            and name_row["source"] == "egen"
            and current.rows["name"].source != "egen"
            and target == (current.contact_member_id, own_name)
            and _given(name_row.get("value"))
            and normalize("name", name_row["value"]) == normalize("name", current.rows["name"].value)
        ):  # the contact person's name sent back is an echo, not a contact outside the register
            name_row = {**name_row, "source": "medlemskap", "value": None}
            rows = {**rows, "name": name_row}
        typed = {}  # the own value each row will hold
        # own values the call changes: only those are set equal to the register's ("Ja, behåll" and echoes are not)
        sent = {
            f
            for f, r in rows.items()
            if r["source"] == "egen"
            and _given(r.get("value"))
            and (current.rows[f].source != "egen" or normalize(f, r["value"]) != normalize(f, current.rows[f].value))
        }
        for field, row in rows.items():
            if row["source"] == "egen":
                # `value` left out: the own value stays (a privacy change, "Ja, behåll")
                kept = current.rows[field].value if current.rows[field].source == "egen" else None
                value = _given(row["value"]) if "value" in row else _given(kept)
                if value:
                    typed[field] = value

        # Every refusal that can depend on the register (the main member's id in from_row included) comes after
        # the 403s, so that a 403 never depends on whether a guess was right.
        if (
            compared
            and not reader
            and (
                {"contact_member", "name", "shown"} & set(patch)
                or any(f not in typed or r.get("answer") or r["shown"].get("source") != "egen" for f, r in rows.items())
            )
        ):  # decision 11: a value from the register is chosen, compared or shown only by those who read it
            raise ContactForbidden("Uppgifter från medlemskapet kan bara väljas av den som ser dem.")

        # the contact asked for (person id, fritext name): the top level, or the name row
        from_row = None
        if name_row and name_row["source"] == "egen":
            from_row = (None, typed.get("name"))  # an own name is a contact outside the register
        elif name_row and current.rows["name"].source == "egen":  # "Använd medlemskapets": the main member
            from_row = (next((p.id for p in persons if p.role == "huvudmedlem"), None), None)
        member, name = from_row or target
        if not compared:  # every row is the herd's own: nothing is fetched, nobody is chosen
            if member is not None or any(r["source"] != "egen" or r.get("answer") for r in rows.values()):
                raise ValueError("Besättningen är inte jämförd med matrikeln: bara egna uppgifter kan ändras.")
            change = False
        else:  # another person, or to or from fritext; a new fritext text is an own-row edit
            change = member != current.contact_member_id or (
                member is None and (name is None) != (current.mode != "fritext")
            )
        if change and not chooses:
            raise ContactForbidden("Bara huvudmedlemmen, genbanksansvarig och admin byter kontaktperson.")
        if from_row and top and from_row != target:
            raise ValueError("contact och contact.rows.name väljer olika kontakter.")
        own_only = not top and all(
            f in typed and not r.get("answer") and r["shown"].get("source") == "egen" for f, r in rows.items()
        )
        if compared and "shown" not in patch and not own_only:
            raise ValueError("contact.shown krävs när kontakten eller en rads källa byts.")

        shown = patch.get("shown")
        if shown is not None and (shown.get("mode"), shown.get("contact_member"), _given(shown.get("name"))) != (
            current.mode,
            current.contact_member_id,
            own_name,
        ):
            raise ContactConflict(STALE)
        # own rows the patch hands over to the register
        switching = {f for f in rows if compared and current.rows[f].source == "egen" and f not in typed}
        for field, row in rows.items():
            now, seen = current.rows[field], row["shown"]
            # as this user's read reports the row (contact_field); a non-reader's form shows own rows only
            expected = (now.source, _given(now.value), getattr(herd, f"{field}_privacy") or "private")
            got = (seen.get("source"), _given(seen.get("value")), seen.get("privacy"))
            if field in switching or row.get("answer"):  # decided against the register's value: it counts
                alternative = None if field == "name" and current.mode == "fritext" and not chooses else now.alternative
                expected, got = (*expected, alternative), (*got, _given(seen.get("alternative")))
            if got != expected or (row.get("answer") and field not in herd.contact_pending):
                raise ContactConflict(STALE)
            if row["source"] == "egen" and "value" not in row and now.source != "egen":
                raise ValueError(f"contact.rows.{field}: value krävs när raden blir egen.")
            # a value on a "medlemskap" row is only an echo of the fetched value the row shows
            if (
                row["source"] == "medlemskap"
                and _given(row.get("value"))
                and (now.source == "egen" or normalize(field, row["value"]) != normalize(field, now.value))
            ):
                raise ValueError(f"contact.rows.{field}: ett annat värde än medlemskapets kan inte hämtas.")
        if change and member is not None and member not in {p.id for p in persons}:
            raise ValueError("Kontaktpersonen måste vara en aktiv person på besättningens medlemskap.")
        if change and member is None and name is None:
            raise ValueError("Välj en kontaktperson eller skriv kontaktens namn.")

        new = Herd(**herd.__data__)
        if (member, name) != (current.contact_member_id, own_name):
            new.contact_member, new.name = member, name
        for field in rows.keys() - {"name"}:
            setattr(new, field, typed.get(field))  # an own value, or none: fetched
        if compared:
            fetched = herd_contact(Herd(**{**new.__data__, **dict.fromkeys(CONTACT_FIELDS[1:])})).rows
            for field in CONTACT_FIELDS[1:]:
                own, register = getattr(new, field), fetched[field].value
                # no own copy of the register's value: one a reader writes, or the new contact person's
                if (
                    own
                    and register
                    and normalize(field, own) == normalize(field, register)
                    and ((reader and field in sent) or (change and field != "physical_address"))
                ):
                    setattr(new, field, None)
        final = herd_contact(new)
        for field, row in rows.items():
            if field in switching:
                # the own value gives way to the register's: only to the value the form showed
                after = final.rows[field].value
                # no alternative: the two were equal, so the value the form showed is the one fetched
                wanted = _given(row["shown"].get("alternative")) or _given(row["shown"].get("value"))
                if row["source"] == "medlemskap" and after is None:
                    raise ContactConflict(STALE)
                if after is not None and normalize(field, after) != normalize(field, wanted):
                    raise ContactConflict(STALE)

        changes = {
            column: new.__data__.get(column)
            for column in ("contact_member", *CONTACT_FIELDS)
            if new.__data__.get(column) != herd.__data__.get(column)
        }
        for field in CONTACT_FIELDS:
            chosen = rows.get(field, {}).get("privacy")
            written = field in typed or (field == "name" and member is None and name is not None)
            # decisions 4 and 14: another value than the one shown starts hidden when it is fetched, when the user
            # did not write it, and after a change of contact person
            if not _keeps_choice(field, current.rows[field].value, final.rows[field].value, change) and (
                final.rows[field].source != "egen" or not written or (change and field != "physical_address")
            ):
                chosen = "private"
            if chosen and chosen != (getattr(herd, f"{field}_privacy") or "private"):
                changes[f"{field}_privacy"] = chosen
        if compared:
            pending = [
                f
                for f in herd.contact_pending
                if final.rows[f].source == "egen"
                and not rows.get(f, {}).get("answer")
                and new.__data__.get(f) == herd.__data__.get(f)
            ]
            if pending != herd.contact_pending:
                changes["contact_pending"] = pending
        if changes:
            for column, value in changes.items():
                setattr(herd, column, value)
            herd.save(only=list(changes))
