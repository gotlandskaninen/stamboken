"""
Postal address helpers — pure functions, no database import,
so utils/database.py can use them for the derived Membership.postal_address.

Swedish postnummer: five digits, canonical form "NNN NN". The paper matrikel's
single "Postadress" column ("623 55 Visby") is split with POSTAL_ADDRESS_RE;
foreign addresses (none today) leave postal_code empty and keep the whole
line in city.
"""

import re

POSTAL_CODE_RE = re.compile(r"^\s*(\d{3})\s?(\d{2})\s*$")
POSTAL_ADDRESS_RE = re.compile(r"^\s*(\d{3})\s?(\d{2})\s+(.+?)\s*$")

INVALID_POSTAL_CODE = "Postnummer ska vara fem siffror"


def normalize_postal_code(value):
    """None/blank → None; "62355" / "623 55" → "623 55"; anything else → ValueError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(INVALID_POSTAL_CODE)
    if not value.strip():
        return None
    match = POSTAL_CODE_RE.match(value)
    if match is None:
        raise ValueError(INVALID_POSTAL_CODE)
    return f"{match.group(1)} {match.group(2)}"


def split_postal_address(value):
    """Legacy "Postadress" → (postal_code, city). Non-parsing → (None, stripped value)."""
    if value is None or not value.strip():
        return None, None
    match = POSTAL_ADDRESS_RE.match(value)
    if match is None:
        return None, value.strip()
    return f"{match.group(1)} {match.group(2)}", match.group(3)


def format_postal_address(postal_code, city):
    """(postal_code, city) → "623 55 Visby", whichever half exists, or None."""
    return " ".join(part for part in (postal_code, city) if part) or None
