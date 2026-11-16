"""
The yearly report's invitation (step 3, Task 8): the scheduler job, a new link, the test mail and their mail kinds.
The mail row holds only ids; the link is made when the mail is sent, so no token is ever stored.
"""

import logging
from datetime import datetime

import utils.arsrapport as arsrapport
import utils.report_code as report_code
import utils.settings as settings
from utils.arsrapport import ArsrapportError
from utils.arsrapport_pdf import register_extract_pdf
from utils.database import DB_PROXY, OUTSIDE_GENEBANK_HERDS, Herd, ReportAccessCode, YearlyReportRoundGenebank
from utils.mail import enqueue_mail, mail_kind

logger = logging.getLogger(__name__)


def _herds(genebank_id):
    query = Herd.select().where(Herd.genebank == genebank_id, Herd.is_active, Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS))
    return query.order_by(Herd.herd)


def _invite_genebank(activation, now):
    round_, count = activation.round, 0
    year = round_.report_year
    with DB_PROXY.atomic():  # all or nothing, so sent_at never says more than was queued
        # A second job on the same activation waits here, then finds it sent: it must not reissue any code.
        locked = (
            YearlyReportRoundGenebank.select().where(YearlyReportRoundGenebank.id == activation.id).for_update().get()
        )
        if locked.sent_at is not None:
            return 0
        for herd in _herds(activation.genebank_id):
            member = report_code.invitation_recipient(herd)
            if member is None:
                continue
            try:
                code = report_code.issue_code(herd, round_, member, now=now)
            except report_code.StaleRecipient:  # the main member changed since the selection: not ours to mail
                continue
            if code.member_id != member.id:  # lost the race to a new_link for the new main member, who got that mail
                continue
            queued = enqueue_mail(
                "arsrapport.inbjudan",
                "member",
                member.id,
                {"code_id": code.id, "year": year},
                ref=("access_code", code.id),
                herd=herd,
                genebank=activation.genebank_id,
                dedupe_key=f"arsrapport.inbjudan:{herd.id}:{year}",
            )
            count += queued is not None
        YearlyReportRoundGenebank.update(sent_at=now).where(YearlyReportRoundGenebank.id == activation.id).execute()
    return count


def send_due_invitations(now: datetime) -> int:
    """Queues the invitations of every activation that is due and still unsent; returns how many mails were queued."""
    today = now.astimezone(arsrapport.STOCKHOLM).date()
    due = (
        YearlyReportRoundGenebank.select()
        .where(YearlyReportRoundGenebank.sent_at.is_null(), YearlyReportRoundGenebank.send_at <= today)
        .order_by(YearlyReportRoundGenebank.id)
    )
    total = 0
    for activation in due:
        if not arsrapport.round_open(activation.round, activation.genebank_id, today):
            continue
        try:
            total += _invite_genebank(activation, now)
        except Exception:  # pylint: disable=broad-except  # the genebank rolled back; the next run retries it
            logger.exception("Queueing the invitations of genebank %s failed", activation.genebank_id)
    return total


def recipients(round_, genebank_id) -> dict:
    """How many of the genebank's active herds the invitation reaches by e-mail, and how many need the paper form."""
    del round_  # the herds and their main members do not depend on the round
    found = [report_code.invitation_recipient(herd) is not None for herd in _herds(genebank_id)]
    return {"med_epost": sum(found), "utan_epost": len(found) - sum(found)}


def new_link(herd, round_, user, *, now: datetime) -> ReportAccessCode:
    """Revokes the herd's active code, issues a new one and mails it to the main member. Takes no report lock."""
    member = report_code.invitation_recipient(herd)
    if member is None:
        raise ArsrapportError(409, "Besättningen har ingen huvudmedlem med e-postadress.")
    try:
        return _replace_link(herd, round_, user, member, now)
    except report_code.StaleRecipient as exc:  # the main member changed after the first check: retryable, not a 500
        raise ArsrapportError(409, "Huvudmedlemmen har just ändrats. Försök igen.") from exc


def _replace_link(herd, round_, user, member, now):
    with DB_PROXY.atomic():
        report_code.require_current(herd, member)  # before the revoke: a stale selection changes nothing
        old = ReportAccessCode.get_or_none(
            ReportAccessCode.herd == herd.id, ReportAccessCode.round == round_.id, ReportAccessCode.revoked_at.is_null()
        )
        if old is not None:
            report_code.revoke(old, now=now)
        code = report_code.issue_code(herd, round_, member, now=now)
        if code.member_id != member.id:  # the main member changed under us: nothing goes to the wrong person
            raise ArsrapportError(409, "Huvudmedlemmen har just ändrats. Försök igen.")
        enqueue_mail(
            "arsrapport.ny_lank",
            "member",
            member.id,
            {"code_id": code.id, "year": round_.report_year},
            ref=("access_code", code.id),
            herd=herd,
            genebank=herd.genebank_id,
            dedupe_key=f"arsrapport.ny_lank:{code.id}",
            created_by=user.id,
        )
    return code


def test_mail(round_, genebank_id, user):
    """The invitation to `user` for the genebank's first herd that has rabbits, with no code and no link."""
    year = round_.report_year
    herd = next((h for h in _herds(genebank_id) if arsrapport.report_list(h, year)), None)
    if herd is None:
        raise ArsrapportError(409, "Genbanken har ingen aktiv besättning med kaniner att visa i provmejlet.")
    return enqueue_mail(
        "arsrapport.inbjudan",
        "user",
        user.id,
        {"prov": True, "year": year, "herd_id": herd.id},
        herd=herd,
        genebank=genebank_id,
        priority=0,  # Å2: the manager waits for it
    )


def _common(herd, round_):
    return {
        "herd": herd.herd,
        "herd_name": herd.herd_name,
        "year": round_.report_year,
        "deadline": f"{round_.deadline:%Y-%m-%d}",
        "end_date": f"{round_.end_date:%Y-%m-%d}",
    }


def _valid_code(params):
    """The mail's code with its herd and round, or None when the link is revoked, expired or no longer the herd's."""
    code = ReportAccessCode.get_or_none(ReportAccessCode.id == params["code_id"])
    if code is None:
        return None
    herd = Herd.get_by_id(code.herd_id)
    return None if report_code.refusal(code, herd, today=arsrapport.today()) else (code, herd, code.round)


@mail_kind("arsrapport.inbjudan", priority=2, category="T")
def _inbjudan(params):
    if params.get("prov"):
        herd, round_ = Herd.get_by_id(params["herd_id"]), arsrapport.get_round(params["year"])
        link = f"{settings.service.host.rstrip('/')}/rapport#prov"  # FA9: no code, no token
    else:
        valid = _valid_code(params)
        if valid is None:
            return None
        code, herd, round_ = valid
        if arsrapport.current_report(herd, round_) is not None:  # already reported on paper or elsewhere
            return None
        link = report_code.code_url(code)
    return {
        **_common(herd, round_),
        "link": link,
        "prov": bool(params.get("prov")),
        "attachments": [(f"registerutdrag-{herd.herd}.pdf", "application/pdf", register_extract_pdf(herd, round_))],
    }


@mail_kind("arsrapport.ny_lank", priority=1, category="T")
def _ny_lank(params):
    valid = _valid_code(params)  # R8: a report already sent does not cancel it; changing or withdrawing needs the link
    if valid is None:
        return None
    code, herd, round_ = valid
    return {**_common(herd, round_), "link": report_code.code_url(code)}
