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

from utils.database import Herd, HerdAccessGrant, Member, Membership, User

CONTACT_FIELDS = ("name", "email", "mobile_phone", "physical_address")
Source = Literal["egen", "person", "medlemskap"]
Mode = Literal["ej_jamford", "person", "fritext", "ingen"]


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


def herd_contacts(herds: Sequence[Herd]) -> dict[int, HerdContact]:
    """The contact of each herd, by herd id, with one query for all of them."""
    compared = [h for h in herds if h.membership_id is not None and h.contact_pending is not None]
    persons = {}  # membership id -> {person id: person}: active persons of active memberships only
    if compared:
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
            .where(
                Member.membership.in_({h.membership_id for h in compared}),
                Member.end_date.is_null(True),
                Membership.membership_status == "active",
            )
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


def is_matrikel_reader(user: User | None, herd: Herd) -> bool:
    """Decision 11: admin, the genebank's manager, and active persons on the herd's active membership
    (main and family members, caretakers with an active grant on the herd). Not the old owner role."""
    if user is None:
        return False
    if user.is_admin or herd.genebank_id in (user.is_manager or []):
        return True
    if herd.membership_id is None:
        return False
    persons = list(
        Member.select(Member.id, Member.role)
        .join(Membership)
        .where(
            Member.user == user.id,
            Member.membership == herd.membership_id,
            Member.end_date.is_null(True),
            Membership.membership_status == "active",
        )
    )
    if any(p.role in ("huvudmedlem", "familjemedlem") for p in persons):
        return True
    caretakers = [p.id for p in persons if p.role == "skotare"]
    return bool(caretakers) and (
        HerdAccessGrant.select()
        .where(
            HerdAccessGrant.member.in_(caretakers),
            HerdAccessGrant.herd == herd.id,
            HerdAccessGrant.revoked_at.is_null(True),
            HerdAccessGrant.valid_until.is_null(True) | (HerdAccessGrant.valid_until >= date.today()),
        )
        .exists()
    )


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
    raise ValueError(f"no normalisation for {field}")
