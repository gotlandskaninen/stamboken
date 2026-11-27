"""
The yearly report's invitation (step 3, Task 8): the scheduler job, a new link, the test mail and their mail kinds.
The mail row holds only ids; the link is made when the mail is sent, so no token is ever stored.
"""

import logging
from datetime import datetime

from peewee import fn

import utils.arsrapport as arsrapport
import utils.login_code as login_code
import utils.report_code as report_code
import utils.settings as settings
from utils.arsrapport import ArsrapportError
from utils.arsrapport_pdf import extract_context, render_pdf, render_text
from utils.database import (
    DB_PROXY,
    OUTSIDE_GENEBANK_HERDS,
    Herd,
    Member,
    ReportAccessCode,
    YearlyReportRound,
    YearlyReportRoundGenebank,
)
from utils.mail import enqueue_mail, mail_kind

logger = logging.getLogger(__name__)


def _herds(genebank_id):
    query = Herd.select().where(Herd.genebank == genebank_id, Herd.is_active, Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS))
    return query.order_by(Herd.herd)


def _invite_genebank(activation, now):
    count = 0
    with DB_PROXY.atomic():  # all or nothing, so sent_at never says more than was queued
        # The round row first, as Dra tillbaka takes it: a moved end_date updates it before the codes, so the two
        # never take the codes in different orders, and each code gets the end_date read here
        round_ = arsrapport._lock_round(activation.round)  # pylint: disable=protected-access
        if not arsrapport.round_open(round_, activation.genebank_id, now.astimezone(arsrapport.STOCKHOLM).date()):
            return 0
        year = round_.report_year
        # A second job waits here before choosing the herds still missing a link.
        locked = (
            YearlyReportRoundGenebank.select().where(YearlyReportRoundGenebank.id == activation.id).for_update().get()
        )
        for herd in _herds(activation.genebank_id):
            report_code.lock_herd_codes(herd)  # serialize the existence check with Ny länk
            member = report_code.invitation_recipient(herd, now=now)
            if member is None:
                logger.warning(
                    "Årsrapport %s: besättning %s saknar huvudmedlem med giltig inloggningsadress", year, herd.id
                )
                continue
            issued = ReportAccessCode.select().where(
                ReportAccessCode.herd == herd.id,
                ReportAccessCode.round == round_.id,
                ReportAccessCode.member == member.id,
            )
            if issued.exists():
                continue
            try:
                code = report_code.issue_code(herd, round_, member, now=now)
            except report_code.StaleRecipient:  # the main member changed since the selection: not ours to mail
                logger.warning("Årsrapport %s: huvudmedlemmen för besättning %s har ändrats", year, herd.id)
                continue
            if code.member_id != member.id:
                logger.warning("Årsrapport %s: koden för besättning %s tillhör en annan huvudmedlem", year, herd.id)
                continue
            queued = enqueue_mail(
                "arsrapport.inbjudan",
                "member",
                member.id,
                {"code_id": code.id, "year": year},
                ref=("access_code", code.id),
                herd=herd,
                genebank=activation.genebank_id,
                dedupe_key=f"arsrapport.inbjudan:{code.id}",
            )
            count += queued is not None
        if locked.sent_at is None:
            locked.sent_at = now
            locked.save(only=[YearlyReportRoundGenebank.sent_at])
    return count


def send_due_invitations(now: datetime) -> int:
    """Queues due invitations, retrying herds without a link while their round is open."""
    if settings.service.demo_instance:
        logger.info("Årsrapportens inbjudningar hoppas över i demomiljön")
        return 0
    today = now.astimezone(arsrapport.STOCKHOLM).date()
    due = (
        YearlyReportRoundGenebank.select()
        .join(YearlyReportRound)
        .where(YearlyReportRoundGenebank.send_at <= today, YearlyReportRound.end_date >= today)
        .order_by(YearlyReportRoundGenebank.id)
    )
    total = 0
    for activation in due:
        try:
            total += _invite_genebank(activation, now)
        except Exception:  # pylint: disable=broad-except  # the genebank rolled back; the next run retries it
            logger.exception("Queueing the invitations of genebank %s failed", activation.genebank_id)
    return total


def recipients(round_, genebank_id) -> dict:
    """How many of the genebank's active herds the invitation reaches by e-mail, and how many need the paper form."""
    del round_  # the herds and their main members do not depend on the round
    herds = _herds(genebank_id)
    reachable = report_code.invitation_members(arsrapport.now()).select(Member.membership).order_by()
    count = fn.COUNT(Herd.id)
    total, with_mail = herds.select(count, count.filter(Herd.membership.in_(reachable))).order_by().tuples().get()
    return {"med_epost": with_mail, "utan_epost": total - with_mail}


def new_link(herd, round_, user, *, now: datetime) -> ReportAccessCode:
    """Revokes the herd's active code, issues a new one and mails it to the main member. Takes no report lock."""
    try:
        return _replace_link(herd, round_, user, now)
    except report_code.StaleRecipient as exc:  # the main member changed after the first check: retryable, not a 500
        raise ArsrapportError(409, "Huvudmedlemmen har just ändrats. Försök igen.") from exc


def _replace_link(herd, round_, user, now):
    with DB_PROXY.atomic():
        # The round row before the codes, as the invitation job: a legacy PATCH of report_year holds the row FOR
        # UPDATE and then updates the codes, which the replacement's insert (a key-share lock on the row) would cross
        round_ = arsrapport._lock_round(round_)  # pylint: disable=protected-access
        report_code.lock_herd_codes(herd)  # then: the recipient is read, and the old link revoked, under it
        member = report_code.invitation_recipient(herd, now=now)
        if member is None:
            raise ArsrapportError(
                409, "Ingen e-postadress kan just nu användas för att logga in som besättningens huvudmedlem."
            )
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


def _link_address(params):
    member = (
        report_code.invitation_members(arsrapport.now())
        .join_from(Member, ReportAccessCode, on=(ReportAccessCode.member == Member.id))
        .join_from(ReportAccessCode, Herd)
        .where(
            ReportAccessCode.id == params["code_id"],
            ReportAccessCode.revoked_at.is_null(),
            Herd.membership == Member.membership,
        )
        .first()
    )
    return member.login_address if member is not None else None


@mail_kind("arsrapport.inbjudan", priority=2, category="T", login_address=_link_address)
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
    extract = extract_context(herd, round_)  # one read for the mail text and the attachment
    host = settings.service.host.rstrip("/")
    return {
        **_common(herd, round_),
        "link": link,
        "login_url": f"{host}/auth/sign-in" if login_code.enabled() else None,  # built at send time, never stored
        "prov": bool(params.get("prov")),
        "utdrag": render_text(extract),
        "attachments": [(f"registerutdrag-{herd.herd}.pdf", "application/pdf", render_pdf(extract))],
    }


@mail_kind("arsrapport.ny_lank", priority=1, category="T", login_address=_link_address)
def _ny_lank(params):
    valid = _valid_code(params)  # R8: a report already sent does not cancel it; changing or withdrawing needs the link
    if valid is None:
        return None
    code, herd, round_ = valid
    return {**_common(herd, round_), "link": report_code.code_url(code)}
