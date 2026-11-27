"""
The yearly report's follow-ups (step 6): the reminders to herds without a report (Å3, Å4), scheduled and by the
manager's button, and the list of herds without a report to the genebank's managers after the deadline (Å5). The
mail rows hold only ids and flags; the link is made when the mail is sent, and the builder checks again then that the
mail is still wanted.

Dates follow the round's deadline (Jonas 2026-11-26, question 2): the first reminder is due on deadline−11 at 07:00
in Stockholm, the second on deadline−2 at 07:00. A reminder delivered for one of the two occasions never goes again,
also if the deadline moves; a queued one is judged again when it is sent. The jobs mail members only by day.

The follow-ups never make a link: only the invitation and "Ny länk" do (report_code.issue_code), so a link still
means the member was invited, and the invitation job never skips a herd because a reminder came first.
"""

import json
import logging
import re
from datetime import datetime, time, timedelta

from peewee import fn

import utils.arsrapport as arsrapport
import utils.inbox as inbox
import utils.login_code as login_code
import utils.report_code as report_code
import utils.settings as settings
from utils.arsrapport import STOCKHOLM, ArsrapportError
from utils.arsrapport_invite import _common, _herds, _link_address
from utils.database import (
    DB_PROXY,
    Genebank,
    Herd,
    Individual,
    MailMessage,
    ReportAccessCode,
    User,
    YearlyHerdReport,
    YearlyReportDraft,
    YearlyReportRound,
    YearlyReportRoundGenebank,
    YearlyReportSubmission,
)
from utils.mail import STOPPED, Later, enqueue_mail, is_address, mail_kind

logger = logging.getLogger(__name__)

REMINDER = "arsrapport.paminnelse"
UNANSWERED = "arsrapport.ej_svarat"
MISSING = "arsrapport.fraga_saknade"
# shortcut: Å5 is caught up for two weeks after it is due, so a round from before step 6 never mails at deploy;
# make it a column on the activation (sent_at) if a list should be resent or tracked.
UNANSWERED_DAYS = 14
SLOTS = {1: 11, 2: 2}  # each scheduled reminder and its days before the deadline
# shortcut: Å22 is caught up for a week after the paper form was entered, so the first deploy asks only about recent
# forms; the status view's "ej angivna" stays the manager's list for older ones.
MISSING_DAYS = 7
SEND_HOUR, LAST_HOUR = 7, 20  # the jobs mail members from 07:00 to 20:59 in Stockholm
OUTSTANDING = ("queued", "sending")
INVITED = ("arsrapport.inbjudan", "arsrapport.ny_lank")
NO_LINK = "Besättningen har ingen giltig länk till sin huvudmedlem. Skicka en ny länk."
REFUSED = {  # why no reminder goes, as the manager's button says it
    "lank": NO_LINK,
    "rundan_stangd": "Rundan är inte öppen för besättningens genbank.",
    "inskickad": "Årsrapporten är redan inskickad.",
    "tillfallet_passerat": "Påminnelsen gäller inte längre.",
}


def reminder_slot(round_, now):
    """
    The scheduled reminder whose interval `now` is in: 1 from deadline−11 at 07:00 until 2 begins, 2 from deadline−2 at
    07:00 through the deadline's day, else None. After a longer outage only the latest is due.
    """
    if round_.deadline is None or now.astimezone(STOCKHOLM).date() > round_.deadline:
        return None
    return max((slot for slot in SLOTS if now >= slot_start(round_, slot)), default=None)


def slot_start(round_, slot):
    return datetime.combine(round_.deadline - timedelta(days=SLOTS[slot]), time(SEND_HOUR), STOCKHOLM)


def daytime(now):
    return SEND_HOUR <= now.astimezone(STOCKHOLM).hour <= LAST_HOUR


def _by_day(now):
    """A builder's member mail waits in the queue until 07:00 when the queue reaches it at night (a relay outage)."""
    if daytime(now):
        return
    local = now.astimezone(STOCKHOLM)
    day = local.date() + timedelta(days=local.hour > LAST_HOUR)
    raise Later(datetime.combine(day, time(SEND_HOUR), STOCKHOLM), "medlemmar får mejl dagtid")


def _sendable(code, herd, today):
    """The link is valid and the queue can send to its member's login address (else it cancels every hour)."""
    return report_code.refusal(code, herd, today=today) is None and is_address(_link_address({"code_id": code.id}))


def _refusal(herd, round_, code, scheduled, slot, now):
    """
    Why the reminder is not wanted now, or None: the one test of the scan, of the recheck before queueing and of the
    builder, so a reminder the builder cancels is not queued again by the next scan.
    """
    today = now.astimezone(STOCKHOLM).date()
    if round_.deadline is None:  # a legacy round: never open for the report's mails
        return "rundan_stangd"
    if code is None or not _sendable(code, herd, today):
        return "lank"
    if not arsrapport.round_open(round_, herd.genebank_id, today):
        return "rundan_stangd"
    if arsrapport.current_report(herd, round_) is not None:
        return "inskickad"
    if scheduled and reminder_slot(round_, now) != slot:
        return "tillfallet_passerat"
    return None


def reminders(round_, herd_ids):
    """The round's reminder rows of the herds, oldest first. A herd has few, so the round is picked out here."""
    rows = MailMessage.select().where(MailMessage.kind == REMINDER, MailMessage.herd.in_(list(herd_ids)))
    return [row for row in rows.order_by(MailMessage.id) if row.params.get("round_id") == round_.id]


def counts(row):
    """
    P4: a row counts unless the builder or the sender cancelled it as no longer wanted; the reminder is then still
    owed and may go again. One a person stopped ("Stoppa") stays stopped, and a failed or bounced one goes again only
    from the status view ("Försök igen").
    """
    return row.status != "cancelled" or row.last_error == STOPPED


def _slots(row):
    """The occasions a reminder covers: the one it was queued in and, by the button, the one it was sent in."""
    sent_in = re.search(r"tillfälle (\d)", row.last_error or "") if row.status == "sent" else None
    return {row.params.get("slot")} | ({int(sent_in.group(1))} if sent_in else set())


def _invited_in(round_, herd, slot):
    """
    An invitation or a new link went, or waits, since the occasion began: it reminds as well, so a late invitation is
    not followed by a reminder within the hour.
    """
    codes = ReportAccessCode.select(ReportAccessCode.id).where(
        ReportAccessCode.herd == herd.id, ReportAccessCode.round == round_.id
    )
    rows = MailMessage.select().where(
        MailMessage.kind.in_(INVITED), MailMessage.ref_type == "access_code", MailMessage.ref_id.in_(codes)
    )
    start = slot_start(round_, slot)
    return any(counts(row) and (row.sent_at or row.next_attempt_at) >= start for row in rows)


def _covered(rows, scheduled, slot, now):
    """
    A reminder now would be one too many: another waits in the queue (a scheduled one only for the current occasion
    `slot`, as an older one is cancelled when sent), one went today, or a scheduled reminder's occasion already had
    one, sent by the button too. One that failed today does not stop the button.
    """
    today = now.astimezone(STOCKHOLM).date()
    for row in filter(counts, rows):
        if row.status in OUTSTANDING and not (row.params.get("scheduled") and row.params.get("slot") != slot):
            return True
        went = row.sent_at or (row.created_at if row.status == "logged" else None)  # logged: the log mode's "sent"
        if went is not None and went.astimezone(STOCKHOLM).date() == today:
            return True
        if scheduled and slot in _slots(row):
            return True
    return False


def _code(herd, round_):
    """The herd's active link for the round, read FOR SHARE under the report's lock (as Skicka reads it), or None."""
    query = ReportAccessCode.select().where(
        ReportAccessCode.herd == herd.id, ReportAccessCode.round == round_.id, ReportAccessCode.revoked_at.is_null()
    )
    return query.for_update("FOR SHARE").first()


def _remind(herd, round_, now, *, scheduled, user=None):
    """
    Under the report's lock, as Skicka: the herd's link, the reasons and the earlier reminders are read, and the
    reminder queued. Returns the mail id, None when it would be one too many, or raises ArsrapportError when none is
    wanted. A link is never made here (see the module docstring).
    """
    slot = reminder_slot(round_, now)  # a reminder by the button counts for the occasion it falls in
    with DB_PROXY.atomic():
        round_ = arsrapport._lock_round(round_)  # pylint: disable=protected-access  # the order of Skicka
        arsrapport.lock_report(round_, herd)
        herd = Herd.get_by_id(herd.id)
        code = _code(herd, round_)
        if (reason := _refusal(herd, round_, code, scheduled, slot, now)) is not None:
            raise ArsrapportError(409, REFUSED[reason])
        rows = reminders(round_, [herd.id])
        if _covered(rows, scheduled, slot, now) or (scheduled and _invited_in(round_, herd, slot)):
            return None
        return enqueue_mail(
            REMINDER,
            "member",
            code.member_id,
            {"round_id": round_.id, "code_id": code.id, "slot": slot, "scheduled": scheduled},
            ref=("access_code", code.id),
            herd=herd,
            genebank=herd.genebank_id,
            # the lock makes it unique; it is the backstop against a writer without it, and follows a cancelled row
            dedupe_key=f"{REMINDER}:{round_.id}:{herd.id}:{rows[-1].id if rows else 0}",
            created_by=user.id if user is not None else None,
            priority=None if scheduled else 1,  # the button: the manager may call the member about it
        )


def send_reminder(herd, round_, user, *, now: datetime) -> int | None:
    """
    The manager's "Skicka påminnelse": the mail id, or None when a reminder already waits in the queue or went today.
    A herd that needs none (reported, round closed, no address) is a 409 that says why. Never in the demo (P2).
    """
    if settings.service.demo_instance:
        raise ArsrapportError(409, "Påminnelser skickas inte från demon.")
    return _remind(herd, round_, now, scheduled=False, user=user)


def send_due_reminders(now: datetime) -> int:
    """
    The hourly job's reminders: for each genebank whose invitations went, the current occasion's reminder to each
    active herd without a report. Only by day in Stockholm, so a catch-up never mails at night.
    """
    if settings.service.demo_instance:
        logger.info("Årsrapportens påminnelser hoppas över i demomiljön")
        return 0
    if not daytime(now):
        return 0
    activations = (
        YearlyReportRoundGenebank.select(YearlyReportRoundGenebank, YearlyReportRound)
        .join(YearlyReportRound)
        .where(YearlyReportRoundGenebank.sent_at.is_null(False), YearlyReportRound.deadline.is_null(False))
        .order_by(YearlyReportRoundGenebank.id)
    )
    total = 0
    for activation in activations:
        if reminder_slot(activation.round, now) is None:
            continue
        for herd in _herds(activation.genebank_id):
            try:
                total += _remind(herd, activation.round, now, scheduled=True) is not None
            except ArsrapportError:
                continue  # reported, or no link the queue can send: the status view shows it
            except Exception:  # pylint: disable=broad-except  # one herd's failure stops no other
                logger.exception("Queueing the reminder of herd %s failed", herd.id)
    return total


@mail_kind(REMINDER, priority=2, category="T", login_address=_link_address)
def _paminnelse(params):
    code = ReportAccessCode.get_or_none(ReportAccessCode.id == params["code_id"])
    if code is None:
        return None
    herd, round_, now = Herd.get_by_id(code.herd_id), code.round, arsrapport.now()
    if _refusal(herd, round_, code, params["scheduled"], params["slot"], now) is not None:
        return None
    _by_day(now)
    draft = YearlyReportDraft.select().where(YearlyReportDraft.herd == herd.id, YearlyReportDraft.round == round_.id)
    slot = reminder_slot(round_, now)
    return {
        **_common(herd, round_),
        "link": report_code.code_url(code),
        "draft": draft.exists(),  # the state when it is sent
        "late": now.astimezone(STOCKHOLM).date() > round_.deadline,
        # Jonas 2026-11-27: with code login on, logging in first is recommended and the link is the alternative
        "login_url": f"{settings.service.host.rstrip('/')}/auth/sign-in" if login_code.enabled() else None,
        # the button's reminder covers the occasion it is sent in too, also if the deadline moves later (_slots)
        "sent_note": f"tillfälle {slot}" if slot is not None and not params["scheduled"] else None,
    }


# Å5: the herds without a report, to the genebank's managers the day after the deadline (D6)

PAPER_STATES = {"blankett_vantar": "blankett väntar på svar", "blankett_inkommen": "blankett inkommen"}
OTHER_STATES = {"paborjad": "påbörjad", "ingen_epost": "ingen e-post", "ej_rapporterad": "ej rapporterad"}


def unanswered_start(round_):
    return datetime.combine(round_.deadline + timedelta(days=1), time(SEND_HOUR), STOCKHOLM)


def unanswered_due(round_, now):
    """Å5 is due from deadline+1 at 07:00 in Stockholm, also if the round has closed since, for UNANSWERED_DAYS."""
    if round_.deadline is None:
        return False
    start = unanswered_start(round_)
    return start <= now < start + timedelta(days=UNANSWERED_DAYS)


def unanswered(round_, genebank_id):
    """P12: the status view's rows of "Ej svarat", so the list, the filter and its count are the same herds."""
    return [row for row in arsrapport.status_view(round_, genebank_id)["rows"] if row["needs_report"]]


def _unanswered_key(round_id, genebank_id, user_id):
    return f"{UNANSWERED}:{round_id}:{genebank_id}:{user_id}"


def send_due_unanswered(now: datetime) -> int:
    """
    The hourly job's Å5: once per round, genebank and manager, only when some herd has not reported. A manager who
    already has the round's list is not asked about again, so the list is read only while someone lacks it.
    """
    if settings.service.demo_instance:
        logger.info("Årsrapportens lista över dem som inte svarat hoppas över i demomiljön")
        return 0
    activations = (
        YearlyReportRoundGenebank.select(YearlyReportRoundGenebank, YearlyReportRound)
        .join(YearlyReportRound)
        .where(YearlyReportRound.deadline.is_null(False))
        .order_by(YearlyReportRoundGenebank.id)
    )
    total = 0
    for activation in activations:
        round_, genebank_id = activation.round, activation.genebank_id
        if not unanswered_due(round_, now):
            continue
        try:
            managers = inbox.queue_workers(genebank_id, managers_only=True)
            keys = {_unanswered_key(round_.id, genebank_id, user.id) for user in managers}
            had = {
                key
                for (key,) in MailMessage.select(MailMessage.dedupe_key)
                .where(MailMessage.dedupe_key.in_(list(keys)))
                .tuples()
            }
            waiting = [user for user in managers if _unanswered_key(round_.id, genebank_id, user.id) not in had]
            if not waiting or not unanswered(round_, genebank_id):
                continue
            for user in waiting:
                queued = enqueue_mail(
                    UNANSWERED,
                    "user",
                    user.id,
                    {"round_id": round_.id, "genebank_id": genebank_id, "user_id": user.id},
                    genebank=genebank_id,
                    dedupe_key=_unanswered_key(round_.id, genebank_id, user.id),
                )
                total += queued is not None
        except Exception:  # pylint: disable=broad-except  # one genebank's failure stops no other
            logger.exception("Queueing the unanswered list of genebank %s failed", genebank_id)
    return total


@mail_kind(UNANSWERED, priority=1, category="T")
def _ej_svarat(params):
    """The list as it is when sent, to a user who still manages the genebank; none when every herd has reported."""
    user = User.get_or_none(User.id == params["user_id"])
    round_ = YearlyReportRound.get_or_none(YearlyReportRound.id == params["round_id"])
    genebank = Genebank.get_or_none(Genebank.id == params["genebank_id"])
    if user is None or round_ is None or genebank is None or not user.is_active:
        return None
    if genebank.id not in (user.is_manager or []):
        return None
    now = arsrapport.now()
    if round_.deadline is not None and now < unanswered_start(round_):  # the deadline moved later meanwhile
        raise Later(unanswered_start(round_), "sista dagen för stödet har flyttats")
    if not unanswered_due(round_, now):
        return None
    rows = unanswered(round_, genebank.id)
    if not rows:
        return None
    return {
        "year": round_.report_year,
        "genebank": genebank.name.lower(),  # the breed in running text (ORDLISTA)
        "deadline": f"{round_.deadline:%Y-%m-%d}",
        "paper": [(row["herd"], PAPER_STATES[row["state"]]) for row in rows if row["state"] in PAPER_STATES],
        "other": [(row["herd"], OTHER_STATES[row["state"]]) for row in rows if row["state"] in OTHER_STATES],
        "link": f"{settings.service.host.rstrip('/')}/stamboken/arsrapport/status/{round_.report_year}"
        f"?genebank_id={genebank.id}&filter=ej_svarat",
    }


# Å22: the rabbits a paper form left out (ej angivna), asked about once per report (D7, spec 5.5)


def _missing_refusal(herd, round_, report, code, now):
    """
    Why Å22 about `report` (one read of it, also for the list) is not wanted now, or None: the one test of the scan,
    the recheck and the builder. It must still be submitted (not withdrawn), from paper, not an ending, and leave
    rabbits unstated.
    """
    today = now.astimezone(STOCKHOLM).date()
    if code is None or not _sendable(code, herd, today):
        return "lank"
    if not arsrapport.round_open(round_, herd.genebank_id, today):
        return "rundan_stangd"
    if report is None or report.status != "submitted":
        return "ny_rapport"
    if not arsrapport.completable(report):
        return "besvarad"
    return None if _paper_since(report) >= now - timedelta(days=MISSING_DAYS) else "for_gammal"


def _paper_since(report):
    """When the report's latest paper submission was entered: Å22 is caught up for MISSING_DAYS after it."""
    query = YearlyReportSubmission.select(fn.MAX(YearlyReportSubmission.created_at)).where(
        YearlyReportSubmission.report == report.id, YearlyReportSubmission.source == "paper"
    )
    return query.scalar()


def _questions(report_ids):
    rows = MailMessage.select().where(
        MailMessage.kind == MISSING,
        MailMessage.ref_type == "yearlyherdreport",
        MailMessage.ref_id.in_(list(report_ids)),
    )
    return list(rows.order_by(MailMessage.id))


def _ask(report, now):
    """Å22 for one report under its lock, as Skicka; the mail id, or None when it is not wanted or already went."""
    herd, round_ = report.herd, report.round
    with DB_PROXY.atomic():
        round_ = arsrapport._lock_round(round_)  # pylint: disable=protected-access  # the order of Skicka
        arsrapport.lock_report(round_, herd)
        herd, report = Herd.get_by_id(herd.id), YearlyHerdReport.get_by_id(report.id)
        code = _code(herd, round_)
        if _missing_refusal(herd, round_, report, code, now) is not None:
            return None
        rows = _questions([report.id])
        if any(map(counts, rows)):  # P4: once per report; only one cancelled as obsolete is asked again
            return None
        return enqueue_mail(
            MISSING,
            "member",
            code.member_id,
            {"report_id": report.id, "code_id": code.id},
            ref=("yearlyherdreport", report.id),
            herd=herd,
            genebank=herd.genebank_id,
            dedupe_key=f"{MISSING}:{report.id}:{rows[-1].id if rows else 0}",
        )


def send_missing_questions(now: datetime) -> int:
    """
    The hourly job's Å22: each submitted report from paper in an open round that leaves rabbits unstated and has not
    had its question. Found after the paper submission commits, never from inside it.
    """
    if settings.service.demo_instance:
        logger.info("Årsrapportens frågor om saknade kaniner hoppas över i demomiljön")
        return 0
    if not daytime(now):
        return 0
    today = now.astimezone(STOCKHOLM).date()
    paper = YearlyReportSubmission.select(YearlyReportSubmission.report).where(YearlyReportSubmission.source == "paper")
    reports = list(
        YearlyHerdReport.select()
        .join(YearlyReportRound)
        .where(
            YearlyHerdReport.status == "submitted",
            YearlyHerdReport.id.in_(paper),
            YearlyReportRound.start_date <= today,
            YearlyReportRound.end_date >= today,
        )
        .order_by(YearlyHerdReport.id)
    )
    asked = {row.ref_id for row in _questions([report.id for report in reports]) if counts(row)}
    total = 0
    for report in reports:
        if report.id in asked or not json.loads(report.data).get("not_stated"):
            continue
        if _paper_since(report) < now - timedelta(days=MISSING_DAYS):  # also in _missing_refusal; skips a lock here
            continue
        try:
            total += _ask(report, now) is not None
        except Exception:  # pylint: disable=broad-except  # one report's failure stops no other
            logger.exception("Queueing the question about report %s failed", report.id)
    return total


@mail_kind(MISSING, priority=1, category="T", login_address=_link_address)
def _fraga_saknade(params):
    """The rabbits still unstated when it is sent, with the link that shows only them."""
    code = ReportAccessCode.get_or_none(ReportAccessCode.id == params["code_id"])
    if code is None:
        return None
    herd, round_ = Herd.get_by_id(code.herd_id), code.round
    report = YearlyHerdReport.get_or_none(YearlyHerdReport.id == params["report_id"])
    if report is None or report.herd_id != herd.id:
        return None
    now = arsrapport.now()
    if _missing_refusal(herd, round_, report, code, now) is not None:
        return None
    _by_day(now)
    missing = json.loads(report.data)["not_stated"]  # the same read as the check: never an empty list
    rabbits = Individual.select(Individual.number, Individual.name).where(Individual.id.in_(missing))
    return {
        **_common(herd, round_),
        "rabbits": [" ".join(filter(None, (r.number, r.name))) for r in rabbits.order_by(Individual.number)],
        "link": report_code.code_url(code),
    }
