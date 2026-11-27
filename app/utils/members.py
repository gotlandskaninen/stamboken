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
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from peewee import JOIN, fn

from utils.database import (
    MatrikelAudit,
    Member,
    MemberChangeRequest,
    Membership,
    PublicationConsentChange,
    User,
    YearlyReportSubmission,
)
from utils.matrikel import ConfirmRequired, LinkError, link_member_user

logger = logging.getLogger(__name__)

CONSENT_KEYS = ("name", "phone", "email", "address")
# the blankett's wording: one consent, one purpose (fråga 33). Bumped 2026-11-16: the question now says Koharen is the
# paper magazine for members only, so the answer covers a narrower scope than "2026-11" did. Bumped 2026-11-18: the
# question says "besättning" where it said "genbank" (same scope), on the form v5 and in the report alike.
# Bumped 2026-11-20: the Ja answer now asks per item that MAY appear (it asked which must not), same stored keys.
CONSENT_TEXT_VERSION = "2026-11-20"  # the profile asks the same question since step 5 (it had "profil-2025")
# Every version of the question that named Koharen's list of active herds and the herd number. An answer to another
# text (the old profile's member directory, "profil-2025") or one without history is no answer to this question: a
# new text that says more applies only after a new answer (5.11). A bump that says more drops the older versions here.
CONSENT_TEXT_VERSIONS = ("2026-11", "2026-11-16", "2026-11-18", CONSENT_TEXT_VERSION)
NEJ = dict.fromkeys(CONSENT_KEYS, False)
STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Only Phase 9-provisioned Workspace addresses may auto-link. The
# /api/auth/google flow enforces this domain, but the flask-dance
# /api/login/<service> flow does NOT — so the helper enforces it itself.
WORKSPACE_DOMAIN = "@gotlandskaninen.se"


def holder_since(membership_ids) -> dict[int, datetime]:
    """When each membership's current main member became it: the latest swap or reactivation (main_member_changed)
    or main member added. Missing: the holder it was created with. One query for any number of memberships."""
    audit = MatrikelAudit
    became = (audit.action == "main_member_changed") | (
        (audit.action == "person_added") & (audit.payload["role"] == "huvudmedlem")
    )
    rows = (
        audit.select(audit.membership, fn.MAX(audit.created_at).alias("since"))
        .where(audit.membership.in_(list(membership_ids)), became)
        .group_by(audit.membership)
    )
    return {row.membership_id: row.since.astimezone() for row in rows}  # created_at is naive server time


def paper_signature(signed_on, received_on, confirmed):
    """Older forms and stored submissions filled a missing signature with the receipt date."""
    return signed_on if confirmed is True or (received_on is not None and signed_on != received_on) else None


def paper_from_holder(signed_on: date | None, since: datetime | None) -> bool:
    """A day-only signature can identify the new holder only from the day after the change."""
    return since is None or (signed_on is not None and signed_on > since.astimezone(STOCKHOLM).date())


def counted_answers(membership_ids) -> set[int]:
    """
    The memberships whose stored answer counts (5.11): its latest publication_consent_change row answers this
    question (CONSENT_TEXT_VERSIONS) and was given since the current main member became it. An answer belongs to
    the person who gave it; also one given before a swap made before this rule existed never counts.
    """
    change, ids = PublicationConsentChange, list(membership_ids)
    last = change.select(fn.MAX(change.id)).where(change.membership.in_(ids)).group_by(change.membership)
    sub = YearlyReportSubmission
    rows = (
        change.select(
            change.membership,
            change.at,
            change.source,
            sub.data["signed_on"],
            sub.data["received_on"],
            sub.data["signed_on_confirmed"].as_json(),
        )
        .join(sub, JOIN.LEFT_OUTER, on=(change.submission_id == sub.id))
        .where(change.id.in_(last), change.text_version.in_(CONSENT_TEXT_VERSIONS))
        .tuples()
    )
    since = holder_since(ids)
    counted = set()
    for membership_id, at, source, signed, received, confirmed in rows:
        start = since.get(membership_id)
        if start is not None and at < start:
            continue
        if start is not None and source == "paper":
            try:
                day = date.fromisoformat(paper_signature(signed, received, confirmed))
            except (TypeError, ValueError):
                day = None
            if not paper_from_holder(day, start):
                continue
        counted.add(membership_id)
    return counted


def stored_consent(row, counted=None) -> dict:
    """The membership's publication_consent JSONB as stored — `{}` when it is not an object, or when the answer does
    not count (counted_answers). A caller with many memberships passes their `counted_answers`; without it the
    membership's own rows are read.

    Anything that is not a dict (a legacy or hand-edited blob) counts as never
    answered rather than as consent.
    """
    raw = row.publication_consent
    if not isinstance(raw, dict) or not raw:
        return {}
    return raw if row.id in (counted if counted is not None else counted_answers([row.id])) else {}


def effective_consent(row, counted=None) -> dict[str, bool]:
    """Normalize stored JSONB to the full-key boolean shape used by consumers.

    v2: takes the Membership row — publication consent governs the matrikel
    entry, not a person.

    Fail-closed: only a literal JSON `true` is consent. The PATCH route refuses
    anything else, but a stored "false"/"ja"/1 from an older or hand-edited
    blob must not publish either — `bool("false")` is True, and the Koharen
    export would print the e-mail.
    """
    raw = stored_consent(row, counted)
    return {k: raw.get(k) is True for k in CONSENT_KEYS}


def consent_answered(row) -> bool:
    """Has the member answered the Koharen question at all?

    `publication_consent = {}`, or an answer to an older text, means *never
    answered* — the export leaves it out, and the profil page submits all four
    keys on the first save so an all-off answer is still recorded as answered.
    """
    raw = stored_consent(row)
    return any(key in raw for key in CONSENT_KEYS)


def consent_from_answer(ja: bool, utom: list[str]) -> dict[str, bool]:
    """The form's answer as the four keys (5.11): Nej is all False, Ja is `name` and every key not in `utom`."""
    return {key: ja and key not in utom for key in CONSENT_KEYS}


def set_consent(
    membership,
    value,
    *,
    source,
    text_version,
    user=None,
    report=None,
    submission=None,
    at=None,
    revoke_waiting=True,
    whole_answer=False,
) -> bool:
    """
    Under the caller's membership lock, revoke a Ja waiting for the link's receipt mail when revoke_waiting is set.
    Record changed consent, every Nej and every whole answer, so older forms respect the holder's exclusions.
    Return whether the consent and its publication_consent_change history row were written (D9, art. 7.1).
    """
    if revoke_waiting:
        revoke_waiting_consent(membership)
    if not whole_answer and value != NEJ and value == stored_consent(membership):
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


def revoke_waiting_consent(membership):
    """A direct Koharen answer stands over a Ja that waits for the report link's receipt mail (5.11)."""
    MemberChangeRequest.update(revoked_at=datetime.now(timezone.utc), revoked_reason="nyare").where(
        MemberChangeRequest.kind == "publicering",
        MemberChangeRequest.member.in_(Member.select(Member.id).where(Member.membership == membership.id)),
        MemberChangeRequest.confirmed_at.is_null(),
        MemberChangeRequest.revoked_at.is_null(),
    ).execute()


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
