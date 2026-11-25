"""
Helpers for Member entity — consent shape.

Accounts are never linked to a Member automatically: an administrator links them in the matrikel.
"""

import logging
from datetime import datetime, timezone

from utils.database import Membership, PublicationConsentChange

logger = logging.getLogger(__name__)

CONSENT_KEYS = ("name", "phone", "email", "address")
# the blankett's wording: one consent, one purpose (fråga 33). Bumped 2026-11-16: the question now says Koharen is the
# paper magazine for members only, so the answer covers a narrower scope than "2026-11" did. Bumped 2026-11-18: the
# question says "besättning" where it said "genbank" (same scope), on the form v5 and in the report alike.
# Bumped 2026-11-20: the Ja answer now asks per item that MAY appear (it asked which must not), same stored keys.
CONSENT_TEXT_VERSION = "2026-11-20"
PROFILE_CONSENT_TEXT_VERSION = "profil-2025"  # the profile's text ("Medlemsmatrikeln trycks i Koharen") for now

# Only Phase 9-provisioned Workspace addresses may auto-link. The
# /api/auth/google flow enforces this domain, but the flask-dance
# /api/login/<service> flow does NOT — so the helper enforces it itself.
WORKSPACE_DOMAIN = "@gotlandskaninen.se"


def stored_consent(row) -> dict:
    """The publication_consent JSONB as stored — `{}` when it is not an object.

    Anything that is not a dict (a legacy or hand-edited blob) counts as never
    answered rather than as consent.
    """
    raw = row.publication_consent
    return raw if isinstance(raw, dict) else {}


def effective_consent(row) -> dict[str, bool]:
    """Normalize stored JSONB to the full-key boolean shape used by consumers.

    v2: takes the Membership row — publication consent governs the matrikel
    entry, not a person.

    Fail-closed: only a literal JSON `true` is consent. The PATCH route refuses
    anything else, but a stored "false"/"ja"/1 from an older or hand-edited
    blob must not publish either — `bool("false")` is True, and the Koharen
    export would print the e-mail.
    """
    raw = stored_consent(row)
    return {k: raw.get(k) is True for k in CONSENT_KEYS}


def consent_answered(row) -> bool:
    """Has the member answered the Koharen question at all?

    `publication_consent = {}` means *never answered* — the export prints
    "ej angivet", and the profil page submits all four keys on the first save
    so an all-off answer is still recorded as answered. One predicate, used by
    both the export and GET /v2/members/me.
    """
    raw = stored_consent(row)
    return any(key in raw for key in CONSENT_KEYS)


def consent_from_answer(ja: bool, utom: list[str]) -> dict[str, bool]:
    """The form's answer as the four keys (5.11): Nej is all False, Ja is `name` and every key not in `utom`."""
    return {key: ja and key not in utom for key in CONSENT_KEYS}


def set_consent(membership, value, *, source, text_version, user=None, report=None, submission=None, at=None) -> bool:
    """
    Writes `value` as the membership's publication consent, with one publication_consent_change row (D9, art. 7.1),
    when it differs from the stored value, `{}` included. Consent only: never the whole row. A report's write names its
    `report` and `submission` ids. The caller holds the membership's lock. Returns whether it wrote.
    """
    if value == stored_consent(membership):
        return False
    membership.publication_consent = value
    membership.save(only=[Membership.publication_consent, Membership.updated_at])
    PublicationConsentChange.create(
        membership=membership.id,
        at=at or datetime.now(timezone.utc),
        value=value,
        text_version=text_version,
        source=source,
        user=user,
        report=report,
        submission_id=submission,
    )
    return True
