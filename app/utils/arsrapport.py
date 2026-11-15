"""
The yearly report v2 (årsrapport): rounds, their activation per genebank, who may report for a herd, the herd's
list (5.2), the report view and the server draft. The routes are in blueprints/arsrapport.py (ADR-0007).
"""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from peewee import JOIN, IntegrityError

import utils.inbox as inbox
from utils.database import (
    DB_PROXY,
    LIFE_SIGN_KINDS,
    OUTSIDE_GENEBANK_HERDS,
    Breeding,
    Color,
    Herd,
    HerdTracking,
    InboxDocument,
    InboxItem,
    Individual,
    YearlyHerdReport,
    YearlyReportDraft,
    YearlyReportRound,
    YearlyReportRoundGenebank,
    YearlyReportSubmission,
    ht_not_voided,
    latest_ht_per_individual,
    not_voided,
)
from utils.reference_population import _alive_by_note

STOCKHOLM = ZoneInfo("Europe/Stockholm")
DATE_FIELDS = ("start_date", "deadline", "end_date")
DRAFT_MAX_BYTES = 256 * 1024
WITHDRAW_DAYS = 7  # fråga 15: owners and caretakers withdraw until 7 days after the first submission
_REPORT_LOCK = 0x48424152  # "HBAR": classid of the advisory lock on a herd's report in a round


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


def lock_report(round_, herd):
    """The advisory lock on (round, herd): every write to the report or the draft takes it first, in a transaction."""
    DB_PROXY.execute_sql("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (_REPORT_LOCK, f"{round_.id}/{herd.id}"))


def current_report(herd, round_):
    return YearlyHerdReport.get_or_none(
        (YearlyHerdReport.herd == herd.id)
        & (YearlyHerdReport.round == round_.id)
        & (YearlyHerdReport.status == "submitted")
    )


def _submissions(report):
    """The report's submissions, oldest first."""
    query = YearlyReportSubmission.select().where(YearlyReportSubmission.report == report.id)
    return list(query.order_by(YearlyReportSubmission.created_at, YearlyReportSubmission.id))


def report_ops(report):
    """The operation ids (str) the report's submissions wrote: the report's own rows (D3b, D4)."""
    return {str(op) for submission in _submissions(report) for op in submission.operation_ids}


def _listed_5_2(herd, last):
    """
    Spec 5.2's list for `herd` on `last` (31 December), with innehav's filters: H holds the rabbit then, it has a
    certificate (an empty paper number is none), is not voided, and is not dead on `last` by date or by note.
    """
    in_herd = HerdTracking.select(HerdTracking.individual).where(HerdTracking.herd == herd.id)
    # Limited to the rabbits that were ever in H before the window function runs, as innehav limits to the genebank.
    holder = latest_ht_per_individual(as_of=last).where(HerdTracking.individual.in_(in_herd)).alias("holder")
    rows = (
        Individual.select(Individual.id, Individual.death_date, Individual.death_note, Breeding.birth_date)
        .join(holder, on=((holder.c.i_id == Individual.id) & (holder.c.rank == 1)))
        .switch(Individual)
        .join(Breeding, JOIN.LEFT_OUTER, on=(Individual.breeding == Breeding.id))
        .where(
            holder.c.herd == herd.id,
            not_voided(),
            (Individual.certificate.is_null(False) & (Individual.certificate != ""))
            | Individual.digital_certificate.is_null(False),
            Individual.death_date.is_null() | (Individual.death_date > last),
        )
    )
    return {row["id"] for row in rows.dicts() if _alive_by_note(row, last)}


def report_list(herd, year, report=None):
    """
    ReportView.rabbits, sorted on number: the 5.2 list plus every rabbit in the report's latest submission (D3b).
    Only rows outside the report's own operations make a rabbit "redan_rapporterad" (an active ATTESTATION dated
    31/12 in H) or "via_flytt" (an active life sign after 31/12, the first of them in `later`).
    """
    last = date(year, 12, 31)
    ids, ops = _listed_5_2(herd, last), set()
    if report is not None:
        submissions = _submissions(report)
        ops = {str(op) for submission in submissions for op in submission.operation_ids}
        ids |= {int(key) for key in (submissions[-1].data.get("rabbits") or {})} if submissions else set()
    rabbits = (
        Individual.select(
            Individual.id,
            Individual.number,
            Individual.name,
            Individual.sex,
            Individual.castration_date,
            Individual.death_date,
            Color.name.alias("color"),
            Breeding.birth_date,
        )
        .join(Breeding, JOIN.LEFT_OUTER, on=(Individual.breeding == Breeding.id))
        .switch(Individual)
        .join(Color, JOIN.LEFT_OUTER, on=(Individual.color == Color.id))
        .where(Individual.id.in_(sorted(ids)))
        .order_by(Individual.number)
    )
    rows = {}
    for rabbit in rabbits.dicts():
        birth, castration, death = rabbit["birth_date"], rabbit["castration_date"], rabbit["death_date"]
        rows[rabbit["id"]] = {
            "id": rabbit["id"],
            "number": rabbit["number"],
            "name": rabbit["name"],
            "sex": rabbit["sex"],
            "color": rabbit["color"],
            "birth_date": _iso(birth),
            "castrated": rabbit["sex"] == "eunuch" or (castration is not None and castration <= last),
            "adult": birth is None or birth < date(year, 1, 1),
            "last_reported": None,
            "death_date": _iso(death) if death is not None and death > last else None,
            "state": "att_valja",
            "later": None,
        }
    signs = (
        HerdTracking.select(
            HerdTracking.individual,
            HerdTracking.herd,
            HerdTracking.kind,
            HerdTracking.herd_tracking_date,
            HerdTracking.operation_id,
        )
        .where(
            HerdTracking.individual.in_(sorted(rows)),
            ht_not_voided(),
            (HerdTracking.kind == "ATTESTATION")
            | (HerdTracking.kind.in_(LIFE_SIGN_KINDS) & (HerdTracking.herd_tracking_date > last)),
        )
        .order_by(HerdTracking.herd_tracking_date, HerdTracking.id)
    )
    for sign in signs.dicts():  # oldest first: the last attestation wins last_reported, the first later sign wins
        row, when = rows[sign["individual"]], sign["herd_tracking_date"]
        if sign["kind"] == "ATTESTATION":
            row["last_reported"] = _iso(when)
        if str(sign["operation_id"]) in ops:
            continue
        if sign["kind"] == "ATTESTATION" and when == last and sign["herd"] == herd.id:
            row["state"], row["later"] = "redan_rapporterad", None
        elif when > last and row["state"] == "att_valja":
            row["state"], row["later"] = "via_flytt", {"kind": sign["kind"], "date": _iso(when)}
    return list(rows.values())


def stored_body(body: dict) -> dict:
    """D10: the body without matrikel, every buyer (kopare), submission_key and revision; a copy, never mutated."""
    stored = {key: value for key, value in body.items() if key not in ("matrikel", "submission_key", "revision")}
    if isinstance(body.get("rabbits"), dict):
        stored["rabbits"] = {
            key: {**entry, "sald": {k: v for k, v in entry["sald"].items() if k != "kopare"}}
            if isinstance(entry, dict) and isinstance(entry.get("sald"), dict)
            else entry
            for key, entry in body["rabbits"].items()
        }
    return stored


def _holds_private(body):
    """A matrikel or a buyer in the body: never stored in a draft (section 6). A null is only stripped."""
    rabbits = body.get("rabbits")
    entries = rabbits.values() if isinstance(rabbits, dict) else ()
    return body.get("matrikel") is not None or any(
        isinstance(entry, dict) and isinstance(entry.get("sald"), dict) and entry["sald"].get("kopare") is not None
        for entry in entries
    )


def _draft(herd, round_):
    return YearlyReportDraft.get_or_none((YearlyReportDraft.herd == herd.id) & (YearlyReportDraft.round == round_.id))


def draft_json(draft, user):
    """ReportView.draft; `own` says whether the asking user saved it last (P59b)."""
    return {
        "data": draft.data,
        "updated_at": _iso(draft.updated_at),
        "submission_key": str(draft.submission_key) if draft.submission_key else None,
        "own": draft.updated_by_user_id == user.id,
    }


def save_draft(herd, round_, access, user, data, updated_at, submission_key, revision):
    """
    The herd's server draft (5.1), saved under the report's lock. `updated_at` is the version the client saw (None
    for a first save) and `revision` the report revision it started from (None when it saw no report). A first save
    needs the submitted report's revision, so a late autosave after Skicka is refused (5.13); a stale version is a
    409 that carries the current draft. Only while the round is open, or after end_date for an editor or a helper on
    paper (D11, P39c); otherwise a 409 with code runda_stangd.
    """
    day, end = today(), round_.end_date
    late_ok = access.editor or access.role == "helper"  # a helper's access always comes through the post
    # round_open on end_date itself: the genebank has activated the round and its dates are set
    late = late_ok and end is not None and day > end and round_open(round_, herd.genebank_id, end)
    if not (round_open(round_, herd.genebank_id, day) or late):
        raise ArsrapportError(409, "Rundan är inte öppen.", code="runda_stangd")
    if not isinstance(data, dict):
        raise ArsrapportError(400, "Utkastet ska vara ett objekt.")
    if _holds_private(data):
        raise ArsrapportError(400, "Utkastet sparar inte dina uppgifter eller köparens uppgifter.")
    stored = stored_body(data)
    if len(json.dumps(stored, ensure_ascii=False).encode()) > DRAFT_MAX_BYTES:
        raise ArsrapportError(400, "Utkastet är för stort.")
    with DB_PROXY.atomic():
        lock_report(round_, herd)
        draft = _draft(herd, round_)
        report = current_report(herd, round_)
        if draft is None and updated_at is None and revision == (report.revision if report else None):
            try:
                with DB_PROXY.atomic():  # a savepoint: a racing first save leaves the transaction usable
                    return YearlyReportDraft.create(
                        herd=herd.id,
                        round=round_.id,
                        data=stored,
                        submission_key=submission_key,
                        updated_at=now().astimezone(timezone.utc),
                        updated_by_user=user.id,
                    )
            except IntegrityError:
                draft = _draft(herd, round_)
        elif draft is not None and draft.updated_at == updated_at:
            # The version always moves on, also when the clock does not.
            draft.updated_at = max(now(), draft.updated_at + timedelta(microseconds=1)).astimezone(timezone.utc)
            draft.data, draft.submission_key, draft.updated_by_user = stored, submission_key, user.id
            draft.updated_by_access_code = None
            draft.save()
            return draft
        if report is not None and draft is None:
            raise ArsrapportError(409, "Rapporten är redan inskickad.", draft=None)
        raise ArsrapportError(
            409, "Rapporten har ändrats på en annan enhet.", draft=draft_json(draft, user) if draft else None
        )


def on_time(report, round_):
    """i_tid: the manager's override if set, else the Stockholm date of received_at on or before the deadline."""
    if report.on_time_override is not None:
        return report.on_time_override
    received = report.received_at
    return bool(received and round_.deadline and received.astimezone(STOCKHOLM).date() <= round_.deadline)


def withdraw_until(report, access, submissions=None):
    """An owner's or caretaker's last instant for Dra tillbaka: the first submission + 7 days; None for the others."""
    if access.role not in ("owner", "caretaker"):
        return None
    submissions = _submissions(report) if submissions is None else submissions
    return submissions[0].created_at + timedelta(days=WITHDRAW_DAYS) if submissions else None


def _report_json(report, round_, access, is_open):
    submissions = _submissions(report)
    until = withdraw_until(report, access, submissions)
    if access.editor:
        can_withdraw = True
    else:
        can_withdraw = access.role != "helper" and is_open and until is not None and now() <= until
    return {
        "id": report.id,
        "status": report.status,
        "source": report.source,
        "revision": report.revision,
        "received_at": _iso(report.received_at),
        "report_date": _iso(report.report_date),
        "on_time": on_time(report, round_),
        "submitted": submissions[-1].data if submissions else None,
        # fråga 16: after end_date owners and caretakers read the report only
        "can_change": is_open or access.editor or access.role == "helper",
        "can_withdraw": can_withdraw,
        "withdraw_until": _iso(until),
    }


def _account_end(account):
    digits = re.sub(r"\D", "", account or "")
    return digits[-2:] or None


def report_view(herd, round_, access, user):
    """ReportView for the herd and the round's year, as `access` sees it (the villkor come in Task 12)."""
    year = round_.report_year
    first, last = date(year, 1, 1), date(year, 12, 31)
    activated = _activations(round_).where(YearlyReportRoundGenebank.genebank == herd.genebank_id).exists()
    is_open = round_open(round_, herd.genebank_id, today())
    report = current_report(herd, round_)
    draft = _draft(herd, round_)
    Mother, Father = Individual.alias(), Individual.alias()
    litters = (
        Breeding.select(
            Breeding.id,
            Breeding.litter_number,
            Breeding.birth_date,
            Mother.number.alias("mother"),
            Father.number.alias("father"),
            Breeding.litter_size,
            Breeding.litter_size6w,
        )
        .join(Mother, JOIN.LEFT_OUTER, on=(Breeding.mother == Mother.id))
        .switch(Breeding)
        .join(Father, JOIN.LEFT_OUTER, on=(Breeding.father == Father.id))
        .where(Breeding.breeding_herd_id == herd.id, Breeding.birth_date.between(first, last))
        .order_by(Breeding.birth_date, Breeding.id)
    )
    ToHerd = Herd.alias()
    # shortcut: a sale is found by from_herd, which older rows may lack; read the holder before it if they matter.
    sales = (
        HerdTracking.select(
            HerdTracking.individual.alias("individual_id"),
            Individual.number,
            ToHerd.herd.alias("to_herd"),
            HerdTracking.herd_tracking_date.alias("date"),
        )
        .join(Individual)
        .switch(HerdTracking)
        .join(ToHerd, on=(HerdTracking.herd == ToHerd.id))
        .where(
            HerdTracking.from_herd == herd.id,
            HerdTracking.kind == "TRANSFER",
            ht_not_voided(),
            HerdTracking.herd_tracking_date.between(first, last),
        )
        .order_by(HerdTracking.herd_tracking_date, HerdTracking.id)
    )
    others = Herd.select(Herd.herd).where(
        Herd.genebank == herd.genebank_id,
        Herd.is_active == True,  # noqa: E712
        Herd.id != herd.id,
        Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS),
    )
    # 5.7: the membership choices are hidden when the main member's membership has another active herd
    other_active = (
        herd.membership_id is not None
        and Herd.select()
        .where(Herd.membership == herd.membership_id, Herd.id != herd.id, Herd.is_active == True)  # noqa: E712
        .exists()
    )
    item = access.item
    return {
        "herd": {
            "id": herd.id,
            "herd": herd.herd,
            "name": herd.herd_name,
            "genebank_id": herd.genebank_id,
            "genebank": herd.genebank.name,
        },
        "year": year,
        "round": {**{key: _iso(getattr(round_, key)) for key in DATE_FIELDS}, "activated": activated, "open": is_open},
        "access": access.role,
        "source": access.source,
        "can_sell": access.can_sell,
        "other_active_herd": other_active,
        "rabbits": report_list(herd, year, report),
        "litters": [{**row, "birth_date": _iso(row["birth_date"])} for row in litters.dicts()],
        "sales": [{**row, "date": _iso(row["date"])} for row in sales.dicts()],
        "herds": sorted(row.herd for row in others),
        "report": _report_json(report, round_, access, is_open) if report else None,
        "draft": draft_json(draft, user) if draft else None,
        "item": {
            "id": item.id,
            "received_at": _iso(item.received_at),
            "state": item.state,
            "account_end": _account_end(herd.bank_account_number),
        }
        if item
        else None,
    }


def my_reports(user):
    """The rounds the genebanks of the user's own herds have activated, newest year first, with the report's status."""
    herds = list(
        Herd.select().where(Herd.id.in_(sorted(user.effective_herd_ids())), Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS))
    )
    activations = list(
        YearlyReportRoundGenebank.select(YearlyReportRoundGenebank, YearlyReportRound)
        .join(YearlyReportRound)
        .where(YearlyReportRoundGenebank.genebank.in_(sorted({herd.genebank_id for herd in herds})))
    )
    submitted = {
        (report.herd_id, report.round_id)
        for report in YearlyHerdReport.select(YearlyHerdReport.herd, YearlyHerdReport.round).where(
            YearlyHerdReport.herd.in_([herd.id for herd in herds]), YearlyHerdReport.status == "submitted"
        )
    }
    day = today()
    reports = [
        {
            "herd": herd.herd,
            "year": row.round.report_year,
            "open": round_open(row.round, herd.genebank_id, day),
            "status": "submitted" if (herd.id, row.round_id) in submitted else None,
            "deadline": _iso(row.round.deadline),
            "end_date": _iso(row.round.end_date),
        }
        for herd in herds
        for row in activations
        if row.genebank_id == herd.genebank_id
    ]
    return sorted(reports, key=lambda report: (-report["year"], report["herd"]))
