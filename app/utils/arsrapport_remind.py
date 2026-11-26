"""
The yearly report's follow-ups (step 6): the reminders to herds without a report (Å3, Å4), scheduled and by the
manager's button, and the list of herds without a report to the genebank's managers after the deadline (Å5). The
mail rows hold only ids and flags; the link is made when the mail is sent, and the builder checks again then that the
mail is still wanted.

Dates follow the round's deadline (Jonas 2026-11-26, question 2): the first reminder is due on deadline−11 at 07:00
in Stockholm, the second on deadline−2 at 07:00. A reminder delivered for one of the two occasions never goes again,
also if the deadline moves; a queued one is judged again when it is sent.
"""

import logging
from datetime import datetime, time, timedelta

import utils.arsrapport as arsrapport
import utils.inbox as inbox
import utils.report_code as report_code
import utils.settings as settings
from utils.arsrapport import STOCKHOLM, ArsrapportError
from utils.arsrapport_invite import _common, _herds, _link_address
from utils.database import (
    DB_PROXY,
    Genebank,
    Herd,
    MailMessage,
    ReportAccessCode,
    User,
    YearlyReportDraft,
    YearlyReportRound,
    YearlyReportRoundGenebank,
)
from utils.mail import STOPPED, enqueue_mail, mail_kind

logger = logging.getLogger(__name__)

REMINDER = "arsrapport.paminnelse"
UNANSWERED = "arsrapport.ej_svarat"
# shortcut: Å5 is caught up for two weeks after it is due, so a round from before step 6 never mails at deploy;
# make it a column on the activation (sent_at) if a list should be resent or tracked.
UNANSWERED_DAYS = 14
SLOTS = {1: 11, 2: 2}  # each scheduled reminder and its days before the deadline
SEND_HOUR = 7
OUTSTANDING = ("queued", "sending")
NO_RECIPIENT = "Ingen e-postadress kan just nu användas för att logga in som besättningens huvudmedlem."
STALE_RECIPIENT = "Huvudmedlemmen har just ändrats. Försök igen."
REFUSED = {  # why no reminder goes, as the manager's button says it
    "lank": NO_RECIPIENT,
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
    starts = {
        slot: datetime.combine(round_.deadline - timedelta(days=days), time(SEND_HOUR), STOCKHOLM)
        for slot, days in SLOTS.items()
    }
    return max((slot for slot, start in starts.items() if now >= start), default=None)


def _refusal(herd, round_, code, scheduled, slot, now):
    """
    Why the reminder is not wanted now, or None: the one test of the scan, of the recheck before queueing and of the
    builder, so a reminder the builder cancels is not queued again by the next scan.
    """
    today = now.astimezone(STOCKHOLM).date()
    if round_.deadline is None:  # a legacy round: never open for the report's mails
        return "rundan_stangd"
    if code is not None and report_code.refusal(code, herd, today=today) is not None:
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
        if scheduled and row.params.get("slot") == slot:
            return True
    return False


def _remind(herd, round_, now, *, scheduled, user=None):
    """
    D8: the herd's code is issued and committed first (issue_code takes the herd's code lock, which is never taken
    under the report's), then everything is read again under the report's lock and the reminder queued. Returns the
    mail id, None when a reminder would be one too many, or raises ArsrapportError when none is wanted.
    """
    slot = reminder_slot(round_, now)  # a reminder by the button counts for the occasion it falls in
    if (reason := _refusal(herd, round_, None, scheduled, slot, now)) is not None:
        raise ArsrapportError(409, REFUSED[reason])
    if _covered(reminders(round_, [herd.id]), scheduled, slot, now):
        return None
    member = report_code.invitation_recipient(herd, now=now)
    if member is None:
        raise ArsrapportError(409, NO_RECIPIENT)
    try:
        with DB_PROXY.atomic():
            round_ = arsrapport._lock_round(round_)  # pylint: disable=protected-access  # before the codes, as new_link
            code = report_code.issue_code(herd, round_, member, now=now)
    except report_code.StaleRecipient as exc:
        raise ArsrapportError(409, STALE_RECIPIENT) from exc
    with DB_PROXY.atomic():
        round_ = arsrapport._lock_round(round_)  # pylint: disable=protected-access  # the order of Skicka
        arsrapport.lock_report(round_, herd)
        code = ReportAccessCode.select().where(ReportAccessCode.id == code.id).for_update("FOR SHARE").get()
        herd = Herd.get_by_id(herd.id)
        if (reason := _refusal(herd, round_, code, scheduled, slot, now)) is not None:
            raise ArsrapportError(409, REFUSED[reason])
        rows = reminders(round_, [herd.id])
        if _covered(rows, scheduled, slot, now):
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
    active herd without a report. Nothing before 07:00 in Stockholm, so a catch-up never mails at night.
    """
    if settings.service.demo_instance:
        logger.info("Årsrapportens påminnelser hoppas över i demomiljön")
        return 0
    if now.astimezone(STOCKHOLM).hour < SEND_HOUR:
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
                continue  # reported, or no address: the status view shows it
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
    draft = YearlyReportDraft.select().where(YearlyReportDraft.herd == herd.id, YearlyReportDraft.round == round_.id)
    return {
        **_common(herd, round_),
        "link": report_code.code_url(code),
        "draft": draft.exists(),  # the state when it is sent
        "late": now.astimezone(STOCKHOLM).date() > round_.deadline,
    }


# Å5: the herds without a report, to the genebank's managers the day after the deadline (D6)

PAPER_STATES = {"blankett_vantar": "blankett väntar på svar", "blankett_inkommen": "blankett inkommen"}
OTHER_STATES = {"paborjad": "påbörjad", "ingen_epost": "ingen e-post", "ej_rapporterad": "ej rapporterad"}


def unanswered_due(round_, now):
    """Å5 is due from deadline+1 at 07:00 in Stockholm, also if the round has closed since, for UNANSWERED_DAYS."""
    if round_.deadline is None:
        return False
    start = datetime.combine(round_.deadline + timedelta(days=1), time(SEND_HOUR), STOCKHOLM)
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
