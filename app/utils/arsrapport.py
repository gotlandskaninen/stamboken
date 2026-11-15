"""
The yearly report v2 (årsrapport): rounds, their activation per genebank, and who may report for a herd.
The routes are in blueprints/arsrapport.py (ADR-0007).
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import utils.inbox as inbox
from utils.database import (
    OUTSIDE_GENEBANK_HERDS,
    InboxDocument,
    InboxItem,
    YearlyReportRound,
    YearlyReportRoundGenebank,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")
DATE_FIELDS = ("start_date", "deadline", "end_date")


class ArsrapportError(Exception):
    """A refusal with its HTTP status; the blueprint turns it into problem(status, title, detail, **extra)."""

    TITLES = {400: "Ogiltig begäran", 403: "Åtkomst nekad", 404: "Hittades inte", 409: "Konflikt"}

    def __init__(self, status, detail, **extra):
        super().__init__(detail)
        self.status, self.title, self.detail, self.extra = status, self.TITLES[status], detail, extra


def now():
    return datetime.now(timezone.utc)


def today():
    return now().astimezone(STOCKHOLM).date()


def default_dates(year):
    """Fråga 7: the round opens 31 December, the support deadline is 31 January, and it closes 30 March."""
    return {"start_date": date(year, 12, 31), "deadline": date(year + 1, 1, 31), "end_date": date(year + 1, 3, 30)}


def get_round(year):
    return YearlyReportRound.get_or_none(YearlyReportRound.report_year == year)


def save_round(year, user, **dates):
    """
    The year's round with `dates` applied: a new round, or a legacy round's missing dates, get the defaults first.
    Only the dates that change are saved, so legacy's is_active is never written (D3) and the genetics trigger
    sees end_date only when it moves.
    """
    if abs(year - today().year) > 1:
        raise ArsrapportError(400, f"Året ska vara {today().year - 1}, {today().year} eller {today().year + 1}.")
    round_ = get_round(year) or YearlyReportRound(report_year=year, created_by=user)
    wanted = {key: getattr(round_, key) or default for key, default in default_dates(year).items()} | dates
    if not wanted["start_date"] <= wanted["deadline"] <= wanted["end_date"]:
        raise ArsrapportError(400, "Rundan öppnar först, sedan kommer sista dagen för stödet och sist stängningen.")
    changed = [key for key in DATE_FIELDS if getattr(round_, key) != wanted[key]]
    for key in changed:
        setattr(round_, key, wanted[key])
    if round_.id is None:
        round_.save()
    elif changed:
        round_.save(only=[getattr(YearlyReportRound, key) for key in changed])
    return round_


def activate(round_, genebank_id, user, send_at=None):
    """
    The genebank's activation of the round; again, the first one, unchanged. `send_at` defaults to the round's
    first day. The round's is_active is never set: it would open legacy's form for the other genebank (D3).
    """
    send_at = send_at or round_.start_date or default_dates(round_.report_year)["start_date"]
    YearlyReportRoundGenebank.insert(
        round=round_.id, genebank=genebank_id, activated_by=user.id, activated_at=now(), send_at=send_at
    ).on_conflict_ignore().execute()
    return YearlyReportRoundGenebank.get(
        (YearlyReportRoundGenebank.round == round_.id) & (YearlyReportRoundGenebank.genebank == genebank_id)
    )


def _activations(round_):
    return YearlyReportRoundGenebank.select().where(YearlyReportRoundGenebank.round == round_.id)


def round_open(round_, genebank_id, on):
    """D11: the genebank has activated the round and `on` is within its dates; a round without dates is never open."""
    if not (round_.start_date and round_.end_date and round_.start_date <= on <= round_.end_date):
        return False
    return _activations(round_).where(YearlyReportRoundGenebank.genebank == genebank_id).exists()


def _iso(value):
    return value.isoformat() if value is not None else None


def round_json(round_):
    """Round. is_active means some genebank has activated it (P5), not legacy's column."""
    rows = list(_activations(round_).order_by(YearlyReportRoundGenebank.genebank))
    names = inbox.person_names([row.activated_by_id for row in rows])
    return {
        "year": round_.report_year,
        **{key: _iso(getattr(round_, key)) for key in DATE_FIELDS},
        "is_active": bool(rows),
        "genebanks": [
            {
                "genebank_id": row.genebank_id,
                "activated_at": _iso(row.activated_at),
                "activated_by": {"id": row.activated_by_id, "name": names[row.activated_by_id]},
                "send_at": _iso(row.send_at),
                "sent_at": _iso(row.sent_at),
            }
            for row in rows
        ],
    }


@dataclass(frozen=True)
class Access:
    role: str  # owner | caretaker | manager | admin | helper
    item: InboxItem | None = None  # paper only: the taken item with an arsblankett document

    @property
    def source(self):
        return "paper" if self.item else "login"

    @property
    def can_sell(self):
        return self.role != "caretaker"  # D12

    @property
    def editor(self):
        return self.role in ("manager", "admin")


def report_access(user, herd, item_id=None):
    """
    The user's right to the herd's report, or None. On paper (`item_id`): the user's taken item for the herd, with
    an arsblankett document, and never a helper's own upload (P24), as InboxGrant.allows says. It reads the item
    without a lock; the writes check it again under inbox.lock_item.
    """
    if herd.herd in OUTSIDE_GENEBANK_HERDS:
        return None
    managed = herd.genebank_id in (user.is_manager or ())
    if item_id is not None:
        item = InboxItem.get_or_none(
            (InboxItem.id == item_id)
            & (InboxItem.herd == herd.id)
            & (InboxItem.state == "tagen")
            & (InboxItem.assigned_to == user.id)
            & InboxItem.ref_type.is_null()
        )
        if item is None or inbox.own_upload(item, user):
            return None
        if not item.documents.where(InboxDocument.doc_type == "arsblankett").exists():
            return None
        helps = herd.genebank_id in (user.is_helper or ())
        role = "admin" if user.is_admin else "manager" if managed else "helper" if helps else None
        return Access(role, item) if role else None
    if user.is_admin:
        return Access("admin")
    if managed:
        return Access("manager")
    if herd.id in user.transfer_herd_ids():
        return Access("owner")
    if herd.id in user.effective_herd_ids():
        return Access("caretaker")
    return None
