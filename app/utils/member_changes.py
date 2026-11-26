"""
Step 5's changes through the report link (spec 5.11 and 6): what "Har något ändrats?" asked for at Skicka, and the
receipt mail's confirmation page, /rapport/andringar#<link_token("andringar", submission id)>. A forwarded link
can ask for a change but never read or make one: a change waits in member_change_request until the matrikel's
mailbox confirms it, at most 14 days. A No, or fewer details for Koharen, goes at once (fråga 27).

Locks: Skicka holds the report's and then the membership's lock when it records; the confirmation page takes the
membership's lock and then the request rows, never a report lock.
"""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone

from flask import current_app

import utils.arsrapport as arsrapport
from utils.arsrapport import ArsrapportError
from utils.database import (
    DB_PROXY,
    MatrikelAudit,
    Member,
    MemberChangeRequest,
    YearlyHerdReport,
    YearlyReportSubmission,
)
from utils.login_code import AddressTaken
from utils.mail import verify_link
from utils.matrikel import set_member_email
from utils.members import (
    CONSENT_TEXT_VERSION,
    consent_from_answer,
    effective_consent,
    set_consent,
    stored_consent,
)

CHANGE_DAYS = 14  # fråga 30
CHANGED = "Uppgifterna har ändrats sedan sidan visades. Kontrollera ändringarna och bekräfta igen."


def _field(row):
    return row.value.get("field", row.kind) if row.kind == "kontakt" else row.kind


def _state(row, now):
    if row.confirmed_at is not None:
        return "bekraftad"
    if row.revoked_at is not None:
        return "inte_jag" if row.revoked_reason == "inte_jag" else "aterkallad"
    return "forfallen" if now >= row.expires_at else "vantar"


def record(herd, membership, member, submission, code, matrikel):
    """
    The link's "Dina uppgifter" at Skicka: only what differs from the matrikel, blank being no change (as on paper).
    Koharen: a No, or what a Ja takes away from an earlier answer, is written now (source "link"); what it adds, or
    a Ja on a membership that never answered, waits. Everything else is one waiting row per field (D5). The caller
    holds the membership's lock and checked that `member` is the code's.
    """
    at = submission.created_at
    expires = at + timedelta(days=CHANGE_DAYS)
    changes = arsrapport._changes(membership, member, arsrapport._contact(matrikel)[0])

    def wait(kind, value):
        MemberChangeRequest.create(
            member=member.id,
            submission=submission.id,
            kind=kind,
            value=value,
            access_code=code.id,
            created_at=at,
            expires_at=expires,
        )

    for name in ("adress", "telefon", "konto"):
        if name in changes:
            wait("konto" if name == "konto" else "kontakt", {"field": name, "new": changes[name]})
    if "epost" in changes:
        wait("epost", {"old": member.email, "new": changes["epost"]["email"]})
    answer = matrikel.get("publicering")
    if answer is not None:
        wanted = consent_from_answer(answer["ja"], answer["utom"])
        narrowed = None
        if stored_consent(membership) or not answer["ja"]:  # a Ja never narrows a question never answered
            current = effective_consent(membership)
            narrowed = {key: allowed and current[key] for key, allowed in wanted.items()}
            set_consent(
                membership,
                narrowed,
                source="link",
                text_version=CONSENT_TEXT_VERSION,
                report=submission.report_id,
                submission=submission.id,
                at=at,
            )
        if narrowed != wanted:
            wait("publicering", {"new": wanted, "text_version": CONSENT_TEXT_VERSION})


def report_changes(report):
    """ReportView.member_details.changes for the link: the report's waiting and expired changes, without values."""
    if report is None:
        return []
    now = arsrapport.now()
    rows = (
        MemberChangeRequest.select()
        .join(YearlyReportSubmission)
        .where(YearlyReportSubmission.report == report.id, MemberChangeRequest.access_code.is_null(False))
        .order_by(MemberChangeRequest.id)
    )
    return [
        {"falt": _field(row), "state": state, "expires_at": row.expires_at.isoformat()}
        for row in rows
        if (state := _state(row, now)) in ("vantar", "forfallen") and row.value  # a purged one says nothing
    ]


def status_flags(round_, herd_ids):
    """
    The status view's flags per herd (5.14), from the round's changes through the link and no value: how many
    changes wait, whether the latest account change waits or expired, and "Det var inte jag".
    """
    now, flags = arsrapport.now(), {}
    rows = (
        MemberChangeRequest.select(MemberChangeRequest, YearlyHerdReport.herd.alias("report_herd"))
        .join(YearlyReportSubmission)
        .join(YearlyHerdReport)
        .where(
            YearlyHerdReport.round == round_.id,
            YearlyHerdReport.herd.in_(list(herd_ids)),
            MemberChangeRequest.access_code.is_null(False),
        )
        .order_by(MemberChangeRequest.id)
        .objects()
    )
    for row in rows:
        herd = flags.setdefault(row.report_herd, {"andring_vantar": 0, "konto": None, "inte_jag": False})
        state = _state(row, now)
        if row.kind == "konto":
            herd["konto"] = state  # the latest account change counts
        elif state == "vantar":
            herd["andring_vantar"] += 1
        herd["inte_jag"] |= state == "inte_jag"
    return {
        herd_id: {
            "andring_vantar": f["andring_vantar"],
            "kontobyte_vantar": f["konto"] == "vantar",
            "kontobyte_forfoll": f["konto"] == "forfallen",
            "inte_jag": f["inte_jag"],
        }
        for herd_id, f in flags.items()
    }


NO_CHANGES = {"andring_vantar": 0, "kontobyte_vantar": False, "kontobyte_forfoll": False, "inte_jag": False}


def self_made_links(herds, since):
    """
    "nytt konto" (5.1, 5.14): per herd, the audit id of its main member's account link when the member made it
    with a code to the matrikel's e-mail (link mode matrikel_epost) on or after `since`, the round's start, and it
    still stands: no later link or unlink of that person, and the same account.
    """
    holders = {
        member.membership_id: member
        for member in Member.select().where(
            Member.membership.in_([herd.membership_id for herd in herds if herd.membership_id]),
            Member.role == "huvudmedlem",
            Member.end_date.is_null(),
            Member.user.is_null(False),
        )
    }
    latest = {}
    if holders and since is not None:
        for audit in (
            MatrikelAudit.select()
            .where(
                MatrikelAudit.membership.in_(list(holders)),
                MatrikelAudit.action.in_(("person_user_linked", "person_user_unlinked")),
                MatrikelAudit.created_at
                >= datetime.combine(since, datetime.min.time()),  # naive server time, as written
            )
            .order_by(MatrikelAudit.id)
        ):
            latest[(audit.membership_id, (audit.payload or {}).get("person_id"))] = audit
    links = {}
    for herd in herds:
        member = holders.get(herd.membership_id)
        audit = latest.get((herd.membership_id, member.id)) if member is not None else None
        if (
            audit is not None
            and audit.action == "person_user_linked"
            and audit.payload.get("source") == "matrikel_epost"
            and audit.payload.get("user_id") == member.user_id
        ):
            links[herd.id] = audit.id
    return links


def revoke_withdrawn(report, now):
    """Dra tillbaka (D7): the report's waiting changes go; what was written or confirmed stays."""
    submissions = YearlyReportSubmission.select(YearlyReportSubmission.id).where(
        YearlyReportSubmission.report == report.id
    )
    MemberChangeRequest.update(revoked_at=now, revoked_reason="tillbaka").where(
        MemberChangeRequest.submission.in_(submissions),
        MemberChangeRequest.confirmed_at.is_null(),
        MemberChangeRequest.revoked_at.is_null(),
    ).execute()


# The confirmation page


def _submission(token):
    """The submission the mail's token names, or the 403 of a link that does not work (never which part failed)."""
    submission_id = verify_link("andringar", token)
    submission = YearlyReportSubmission.get_or_none(YearlyReportSubmission.id == (submission_id or 0))
    if submission is None:
        raise ArsrapportError(403, arsrapport.LINK_INVALID, code="lank_ogiltig")
    return submission


def _context(submission, *, lock):
    """
    (herd, membership, member, rows): the submission's changes through the link and the herd's main member now,
    under the membership's lock and then the rows' with `lock`. A new main member, or a herd moved to another
    membership, ends the page (D7).
    """
    herd = YearlyHerdReport.get_by_id(submission.report_id).herd
    if lock:
        membership, member = arsrapport._lock_matrikel(herd)
    else:
        membership, member = herd.membership, arsrapport._main_member(herd)
    query = (
        MemberChangeRequest.select()
        .where(MemberChangeRequest.submission == submission.id, MemberChangeRequest.access_code.is_null(False))
        .order_by(MemberChangeRequest.id)
    )
    rows = list(query.for_update() if lock else query)
    if not rows or member is None or any(row.member_id != member.id for row in rows):
        raise ArsrapportError(403, arsrapport.LINK_INVALID, code="lank_ogiltig")
    return herd, membership, member, rows


def _address(parts):
    street, postal, city = (parts.get(key) for key in ("address", "postal_code", "city"))
    return ", ".join(text for text in (street, " ".join(t for t in (postal, city) if t)) if text) or None


def _account(columns):
    digits = re.sub(r"\D", "", columns.get("bank_account_number") or "")
    return f"••••{digits[-4:]}" if digits else None


def _consent(value):
    if not value or not any(value.values()):
        return "Nej" if value else None
    left_out = [label for key, label in arsrapport.CONSENT_LABELS.items() if not value.get(key)]
    return "Ja" + (f", utan {' och '.join(left_out)}" if left_out else "")


def _shown(row, membership, member):
    """(now, new): what the matrikel holds and what the row asks for, as the page shows them, the account masked."""
    new = row.value.get("new")
    field = _field(row)
    if field == "adress":
        now = {part: getattr(membership, part) for part in new}
        return _address(now), _address(new)
    if field == "telefon":
        return member.phone, new["phone"]
    if field == "epost":
        return member.email, new
    if field == "konto":
        return _account({"bank_account_number": membership.bank_account_number}), _account(new)
    return _consent(stored_consent(membership)), _consent(new)


def _entries(membership, member, rows, now):
    entries = []
    for row in rows:
        state = _state(row, now)
        shown = _shown(row, membership, member) if state == "vantar" and row.value else (None, None)
        done = (row.confirmed_at or row.revoked_at or row.expires_at).astimezone(timezone.utc).isoformat()
        entries.append(
            {"id": row.id, "falt": _field(row), "state": state, "nu": shown[0], "nytt": shown[1], "datum": done}
        )
    return entries


def _version(entries):
    """D6, U5: what the page showed, as an HMAC, so a POST after any other change is a 409 and no value is sent."""
    canonical = json.dumps(entries, sort_keys=True, ensure_ascii=False)
    return hmac.new(current_app.secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()[:32]


def _view(herd, entries):
    return {"herd": herd.herd, "changes": entries, "version": _version(entries)}


def view(token):
    """GET's answer: never writes."""
    herd, membership, member, rows = _context(_submission(token), lock=False)
    return _view(herd, _entries(membership, member, rows, arsrapport.now()))


def confirm(token, *, account, version):
    """
    Bekräfta: every waiting change of the submission, the account only with its own tick (`account`), under the
    membership's lock and against what the page showed (`version`, else 409). An e-mail goes through
    set_member_email as another's change (seven days' wait, notice to the old address), and only while the
    matrikel still holds the address it replaces. Confirming a change revokes the member's older waiting change
    of the same field (5.11), never a newer one.
    """
    with DB_PROXY.atomic():
        submission = _submission(token)
        herd, membership, member, rows = _context(submission, lock=True)
        now = arsrapport.now()
        if not hmac.compare_digest(version or "", _version(_entries(membership, member, rows, now))):
            raise ArsrapportError(409, CHANGED)
        for row in rows:
            if _state(row, now) != "vantar" or (row.kind == "konto" and not account):
                continue
            field, new = _field(row), row.value["new"]
            payload = {"source": "link", "request_id": row.id, "access_code_id": row.access_code_id}
            if row.kind == "epost":
                if not arsrapport._same("email", member.email, (row.value["old"] or "").lower()):
                    row.revoked_at, row.revoked_reason = now, "andrad"
                    row.save(only=[MemberChangeRequest.revoked_at, MemberChangeRequest.revoked_reason])
                    continue
                old = member.email
                try:  # its own savepoint: a refused address leaves the other changes to confirm
                    member.email = set_member_email(member, new, None, by="other").email
                except AddressTaken:
                    row.revoked_at, row.revoked_reason = now, "andrad"  # the page says it no longer applies
                    row.save(only=[MemberChangeRequest.revoked_at, MemberChangeRequest.revoked_reason])
                    continue
                payload |= {"before": {"email": old}, "after": {"email": member.email}}
                arsrapport.save_contact(membership, member, {"epost": {"email": new}}, None, payload)
            elif row.kind == "publicering":
                set_consent(
                    membership,
                    new,
                    source="link",
                    text_version=row.value.get("text_version", CONSENT_TEXT_VERSION),
                    report=submission.report_id,
                    at=now,
                    revoke_waiting=False,
                )
            else:
                arsrapport.save_contact(membership, member, {field: new}, None, payload)
                if field == "konto":
                    arsrapport.account_notice(herd, member, f"andring:{row.id}")
            row.confirmed_at = now
            row.save(only=[MemberChangeRequest.confirmed_at])
            _revoke_older(row, field, now)
        return _view(herd, _entries(membership, member, rows, now))


def _revoke_older(row, field, now):
    older = MemberChangeRequest.select().where(
        MemberChangeRequest.member == row.member_id,
        MemberChangeRequest.kind == row.kind,
        MemberChangeRequest.id < row.id,
        MemberChangeRequest.confirmed_at.is_null(),
        MemberChangeRequest.revoked_at.is_null(),
    )
    ids = [other.id for other in older if _field(other) == field]
    if ids:
        MemberChangeRequest.update(revoked_at=now, revoked_reason="nyare").where(
            MemberChangeRequest.id.in_(ids)
        ).execute()


def not_me(token):
    """ "Det var inte jag": the submission's changes not yet written are revoked, and the status view says so."""
    with DB_PROXY.atomic():
        herd, membership, member, rows = _context(_submission(token), lock=True)
        now = arsrapport.now()
        for row in rows:
            if row.confirmed_at is None and row.revoked_at is None:
                row.revoked_at, row.revoked_reason = now, "inte_jag"
                row.save(only=[MemberChangeRequest.revoked_at, MemberChangeRequest.revoked_reason])
        return _view(herd, _entries(membership, member, rows, now))
