"""
The yearly report's personal link (step 3): one `report_access_code` per herd and round, its token and its validity.
The token is `mail.link_token("rapport", code.id)`: no code or hash of it is stored.
"""

from dataclasses import dataclass
from datetime import date, datetime

from peewee import IntegrityError

import utils.settings as settings
from utils.database import DB_PROXY, Herd, Member, ReportAccessCode
from utils.mail import link_token, verify_link


def invitation_recipient(herd: Herd) -> Member | None:
    """
    FA11: who the herd's invitation goes to, and who a code must have been issued to. The herd's current main
    member, when the membership is active and the member has an e-mail address. A pending or friexemplar membership
    gets no link.
    """
    # Late import: inbox pulls in half the app, and arsrapport imports this module.
    import utils.inbox as inbox  # pylint: disable=import-outside-toplevel

    member = inbox.herd_holder(herd.id)
    if member is None or member.membership.membership_status != "active" or not (member.email or "").strip():
        return None
    return member


class StaleRecipient(Exception):
    """The member a code was to be issued to is not the herd's main member any more."""


_HERD_CODE_LOCK = 0x48424343  # "HBCC": classid of the advisory lock on a herd's access codes


def lock_herd_codes(herd: Herd) -> None:
    """
    Serializes issuing and replacing a herd's link (issue_code, new_link) until the transaction ends, taken before the
    recipient is read and before any revoke, so a stale selection cannot revoke the code of the member who replaced it.
    Lock order: this lock first, then code rows. It is never taken under the report lock, and nothing holding it takes
    the report lock, so a submission (report lock, then FOR SHARE on its code row in _recheck_code) can wait for a
    revoke to commit but never form a cycle with it.
    """
    DB_PROXY.execute_sql("SELECT pg_advisory_xact_lock(%s, %s)", (_HERD_CODE_LOCK, herd.id))


def require_current(herd: Herd, member: Member) -> None:
    # Late import, as in invitation_recipient.
    import utils.inbox as inbox  # pylint: disable=import-outside-toplevel

    holder = inbox.herd_holder(herd.id)
    if holder is None or holder.id != member.id:
        raise StaleRecipient(f"member {member.id} is not herd {herd.id}'s main member")


def _active(herd, round_):
    return ReportAccessCode.get_or_none(
        ReportAccessCode.herd == herd.id, ReportAccessCode.round == round_.id, ReportAccessCode.revoked_at.is_null()
    )


def issue_code(herd: Herd, round_, member: Member, *, now: datetime) -> ReportAccessCode:
    """
    The herd's active code for the round, or a new one that expires on the round's end date. A code issued to an
    earlier main member is revoked and replaced, since refusal would reject it. Two calls at once: the partial unique
    index lets one insert win, and the other returns the winner's code.
    """
    with DB_PROXY.atomic():
        lock_herd_codes(herd)
        require_current(herd, member)  # before anything is revoked: a stale caller changes nothing
        code = _active(herd, round_)
        if code is not None and code.member_id != member.id:
            revoke(code, now=now)
            code = None
        if code is None:
            try:
                with DB_PROXY.atomic():  # a savepoint: the lost race leaves the transaction usable
                    code = ReportAccessCode.create(
                        herd=herd.id, round=round_.id, member=member.id, expires_at=round_.end_date, created_at=now
                    )
            except IntegrityError:
                code = _active(herd, round_)
                if code is None:
                    raise
        return code


def revoke(code: ReportAccessCode, *, now: datetime) -> None:
    ReportAccessCode.update(revoked_at=now).where(
        ReportAccessCode.id == code.id, ReportAccessCode.revoked_at.is_null()
    ).execute()
    code.revoked_at = code.revoked_at or now


def code_url(code: ReportAccessCode) -> str:
    return f"{settings.service.host.rstrip('/')}/rapport#{link_token('rapport', code.id)}"


def resolve(token: str) -> ReportAccessCode | None:
    code_id = verify_link("rapport", token)
    return ReportAccessCode.get_or_none(ReportAccessCode.id == code_id) if code_id else None


def refusal(code: ReportAccessCode, herd: Herd, *, today: date) -> str | None:
    """
    None when the code is valid (E4), else a reason for the log, never shown. Validity follows the round's end date
    (R10), not the column, and the recipient is the one the invitation would go to now (FA11).
    """
    if code.revoked_at is not None:
        return "aterkallad"
    end_date = code.round.end_date
    if end_date is None or today > end_date:
        return "utgangen"
    if not herd.is_active:
        return "inaktiv"
    recipient = invitation_recipient(herd)
    if recipient is None:
        return "ingen_mottagare"
    if recipient.id != code.member_id:
        return "ny_huvudmedlem"
    return None


@dataclass(frozen=True)
class CodeActor:
    """A link standing in for a user wherever the report and the command layer name an actor."""

    code: ReportAccessCode
    id = None
    is_admin = False
    # frozensets, not tuples: roles_for does set arithmetic on them (R1, R1b).
    is_manager = frozenset()
    is_helper = frozenset()

    @property
    def access_code_id(self) -> int:
        return self.code.id

    @property
    def username(self) -> str:
        return f"länk {self.code.herd.herd}/{self.code.round.report_year}"

    def transfer_herd_ids(self) -> frozenset:
        return frozenset()

    def effective_herd_ids(self) -> frozenset:
        return frozenset()

    def can_edit(self, _) -> bool:
        return False


def actor_key(actor) -> tuple[str, int]:
    """R2: an actor is a user or a code, never compared by id alone."""
    code_id = getattr(actor, "access_code_id", None)
    return ("code", code_id) if code_id is not None else ("user", actor.id)
