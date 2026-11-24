"""
Helpers for Member entity — consent shape and User auto-linking.

Auto-link policy: `try_auto_link_member` is called ONLY from the Google
OAuth callback in app/herdbook.py. Import and approve MUST NOT call it —
they must not set Member.user_id or grant owner privileges. Rationale:
automatic linking requires proof of email ownership in the same
authentication session, which only OAuth provides.

No locks and no transaction live here: the write goes
through utils.matrikel.link_member_user(), the single lock-owning operation
that writes member.user_id — it opens its own transaction and takes
membership → user → person FOR UPDATE itself. Callers pass ids only.
"""

import logging
from datetime import datetime, timezone

from utils.database import Member, Membership, PublicationConsentChange, User
from utils.matrikel import ConfirmRequired, LinkError, link_member_user

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


def try_auto_link_member(member: Member, user: User) -> bool:
    """
    Link `member` to `user`, the account that just signed in with an
    OAuth-verified address equal to `member.workspace_email` (the caller
    matched it), if member.user is unset. The user is never looked up
    again by the self-editable User.email. Herd rights are NOT granted here
    (Member Model v2): effective access is derived at check time via
    User.effective_herd_ids(), so a main-member swap, person removal or
    herd reassignment applies immediately, with nothing stale left in
    the privileges JSON.

    Returns True if a link was made.

    NOTE: matches against `workspace_email`, NOT the contact `email`.
    Contact email is what the applicant typed on /ansok; workspace email
    is the @gotlandskaninen.se login that Phase 9 provisions. Auto-link
    requires OAuth-verified email ownership, which only the workspace
    address can guarantee. Non-workspace-domain addresses are refused
    outright.
    """
    if member.user_id:
        return False
    if not member.workspace_email:
        return False

    workspace_email = member.workspace_email.strip().lower()
    if not workspace_email.endswith(WORKSPACE_DOMAIN):
        # ids only: the refused address is by construction a private one.
        logger.warning(
            "refusing auto-link for member=%s: workspace_email is not a %s address",
            member.id,
            WORKSPACE_DOMAIN,
        )
        return False

    try:
        link_member_user(member.id, user.id, actor=user, mode="oauth")
    except ConfirmRequired as needs:
        logger.warning(
            "refusing auto-link for member=%s: would convey herds %s — left for the matrikel-admin flow",
            member.id,
            [h["herd"] for h in needs.conveys],
        )
        return False
    except LinkError as err:
        # ids only: err.detail names the current holder and the membership
        # number for the admin UI — that PII must never reach the log.
        logger.info(
            "auto-link skipped for member=%s: %s (holder_person_id=%s)",
            member.id,
            err.title,
            err.extensions.get("holder_person_id"),
        )
        return False
    logger.info("auto-linked member=%s user=%s", member.id, user.id)
    return True
