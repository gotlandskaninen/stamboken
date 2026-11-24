"""Recognize explicitly labelled billing addresses in register notes."""

import re

from utils.postal import normalize_postal_code

_LABEL = re.compile(r"\b(?:faktura(?:adress|mottagare)?|fakt\.)(?:[ \t]+till)?(?=[:\s]|$)", re.I)
_REVOKED = re.compile(
    r"\b(?:gäller\s+(?:inte|ej)|(?:inte|ej)\s+(?:längre|användas)|återkall\w*|ny\s+fakturaadress|använd\s+postadressen)\b",
    re.I,
)
# Require a separator between recipient and street, a recognizable street or
# box with a number, and a complete postal town. Ignore less certain layouts.
_ADDRESS = re.compile(
    r"""
    (?:[ \t]*:)?\s*
    (?P<billing_name>[A-ZÅÄÖÉÜ][\w .&'’-]*)[,;\r\n]\s*
    (?P<billing_address>
        (?i:box|[\w .'’-]*?(?:gatan?|väg(?:en)?|gränd(?:en)?|torg(?:et)?|allén?|stig(?:en)?|backen?|gård(?:en)?))
        [ ][0-9]+(?:[ ]?[A-Za-z])?
    )
    (?:\s*[,;]\s*|\s+)
    (?P<billing_postal_code>[0-9]{3}[ ]?[0-9]{2})[ \t]+
    (?P<billing_city>[A-ZÅÄÖÉÜ][^\W\d_]*(?:[ -][A-ZÅÄÖÉÜ][^\W\d_]*)*)
    \.?[ \t]*(?=[,;|\r\n]|$)
    """,
    re.VERBOSE,
)
_DETAIL = re.compile(r"[ \t]*(?:[,;\n]|\r\n?)[ \t]*(e-post|ref\.?|(?:faktura)?referens)[ \t]*:([^,;|\r\n]*)", re.I)


def parse_billing_note(note: str) -> tuple[dict, str] | None:
    """Return proposed fields and the exact supporting excerpt for a single address."""
    labels = list(_LABEL.finditer(note))
    if len(labels) != 1 or _REVOKED.search(note):
        return None
    label = labels[0]
    prefix = note[: label.start()].rstrip(" \t")
    if prefix and prefix[-1] not in ",;\n|":
        return None
    address = _ADDRESS.match(note, label.end())
    if not address:
        return None
    fields = {key: value.strip() for key, value in address.groupdict().items()}
    fields["billing_postal_code"] = normalize_postal_code(fields["billing_postal_code"])
    end = address.end()
    while detail := _DETAIL.match(note, end):
        key = "billing_email" if detail[1].lower() == "e-post" else "billing_reference"
        value = detail[2].strip().rstrip(".,").rstrip()
        if key in fields or len(value.split()) != 1:
            return None
        fields[key] = value
        end = detail.end()
    return fields, note[label.start() : end].strip()
