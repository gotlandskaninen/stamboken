"""Organization fields of a membership, shared by creation and partial updates."""

import re


class OrganizationValidationError(ValueError):
    """Invalid organization details supplied by the matrikel administrator."""


def parse_organization_fields(body: dict, membership=None) -> dict:
    """Return supplied fields, checking their combined values against the locked membership on PATCH."""
    updates = {}
    for field, label in (("organization_name", "Organisationsnamn"), ("organization_number", "Organisationsnummer")):
        if field in body:
            raw = body[field]
            if raw is not None and not isinstance(raw, str):
                raise OrganizationValidationError(f"{label} måste vara text")
            updates[field] = (raw or "").strip() or None
    if not updates:
        return updates

    name = updates.get("organization_name", membership.organization_name if membership else None)
    number = updates.get("organization_number", membership.organization_number if membership else None)
    if name and len(name) > 200:
        raise OrganizationValidationError("Organisationsnamnet får vara högst 200 tecken")
    if number:
        if not name:
            raise OrganizationValidationError("Ange ett organisationsnamn för att spara organisationsnumret")
        if not re.fullmatch(r"[0-9]{6}-[0-9]{4}", number):
            raise OrganizationValidationError("Organisationsnumret ska ha formatet NNNNNN-NNNN")
        if number[2] < "2":
            raise OrganizationValidationError("Den tredje siffran i organisationsnumret måste vara minst 2")
        digits = [int(char) for char in number if char != "-"]
        for i in range(0, 10, 2):
            doubled = digits[i] * 2
            digits[i] = doubled - 9 if doubled > 9 else doubled
        if sum(digits) % 10:
            raise OrganizationValidationError("Organisationsnumrets kontrollsiffra stämmer inte")
    return updates
