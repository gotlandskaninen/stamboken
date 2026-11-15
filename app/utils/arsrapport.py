"""
The yearly report v2 (årsrapport): rounds, their activation per genebank, who may report for a herd, the herd's
list (5.2), the report view, the server draft, the submission and its effects on the register, and the dry run.
The routes are in blueprints/arsrapport.py (ADR-0007).
"""

import calendar
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from peewee import JOIN, IntegrityError

import utils.inbox as inbox
from utils.database import (
    DB_PROXY,
    LIFE_SIGN_KINDS,
    OUTSIDE_GENEBANK_HERDS,
    Bodyfat,
    Breeding,
    Color,
    Herd,
    HerdTracking,
    InboxDocument,
    InboxItem,
    Individual,
    IndividualCommand,
    Weight,
    YearlyHerdReport,
    YearlyReportDraft,
    YearlyReportRound,
    YearlyReportRoundGenebank,
    YearlyReportSubmission,
    coerce_date,
    ht_not_voided,
    ht_order_desc,
    ht_sort_key,
    latest_ht_per_individual,
    not_voided,
)
from utils.herd_tracking import HerdTrackingInvalid, buyer_contact_fields, latest_death_op, reject_contact_details
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


# The submission (the plan's body shape; section 6 for `report`)

CHOICES = ("kvar", "dod", "sald", "ej_angiven")
BODY_KEYS = (
    "submission_key",
    "revision",
    "reason",
    "rabbits",
    "ending_genbank",
    "membership_after_end",
    "health",
    "diseases",
    "defects",
    "message",
)
PAPER_KEYS = ("inbox_item_id", "received_on", "signed_on", "matrikel")
ENTRY_KEYS = ("val", "vikt", "ej_vagd", "hull", "dod", "sald")
DISEASES = ("myxomatos", "rvhd", "koccidios", "annat")
TEXT_LIMITS = {
    "reason": 500,
    "anteckning": 500,
    "beskrivning": 500,
    "annat.namn": 100,
    "alder": 50,
    "ej_vagd": 200,
    "message": 2000,
}
_VIKT = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class RabbitEntry:
    individual_id: int
    val: str
    vikt: float | None
    ej_vagd: str | None
    hull: str | None
    dod: dict | None  # {ar, manad, dag, slaktad, anteckning}
    sald: dict | None  # {till, ar, manad, dag, kopare}: kopare is kopare's buyer object or None


@dataclass(frozen=True)
class Submission:
    key: uuid.UUID | None
    revision: int | None
    reason: str | None
    rabbits: dict[int, RabbitEntry]
    report: dict  # yearlyherdreport.data (section 6); not_weighed and not_stated come from the rabbits
    paper: dict | None  # inbox_item_id, received_on, signed_on (default received_on), matrikel


def _bad(field_, detail):
    return ArsrapportError(400, detail, field=field_)


def _is_int(value):
    return type(value) is int  # True is an int too


def _keys(value, allowed, field_):
    """`value` as an object without keys outside `allowed`."""
    if not isinstance(value, dict):
        raise _bad(field_, "Fältet ska vara ett objekt.")
    if unknown := sorted(map(str, set(value) - set(allowed))):
        raise _bad(field_, f"Okända fält: {', '.join(unknown)}.")
    return value


def _text(value, field_):
    """Free text, stripped, within its limit and without phone numbers or e-mail addresses; blank is None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _bad(field_, "Fältet ska vara text.")
    value = value.strip()
    if len(value) > TEXT_LIMITS[field_]:
        raise _bad(field_, f"Texten får vara högst {TEXT_LIMITS[field_]} tecken.")
    try:
        reject_contact_details(value)
    except HerdTrackingInvalid as exc:
        raise _bad(field_, "Skriv inga telefonnummer eller e-postadresser här.") from exc
    return value or None


def _vikt(value):
    """D17: "2,8", "2.8" or a number, as a float; its range is check's (vikt_ogiltig)."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and _VIKT.fullmatch(value.strip()):  # float() alone takes "nan" and "1e3"
        return float(value.strip().replace(",", "."))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < 1e6:  # not nan, inf, 10**400
        return float(value)
    raise _bad("vikt", "Ange vikten i kilo, till exempel 2,8.")


def _month(value, field_, extra):
    """{ar, manad, dag|null} of a real date, the day optional (5.3); the keys of `extra` are the caller's."""
    value = _keys(value, ("ar", "manad", "dag", *extra), field_)
    ar, manad, dag = value.get("ar"), value.get("manad"), value.get("dag")
    try:
        if not (_is_int(ar) and _is_int(manad) and (dag is None or _is_int(dag))):
            raise ValueError
        date(ar, manad, 1 if dag is None else dag)
    except (ValueError, OverflowError) as exc:
        raise _bad(field_, "Ange år och månad, och dagen om den är känd.") from exc
    return {"ar": ar, "manad": manad, "dag": dag}


def _entry(key, raw):
    """One rabbit's answer, or None without a choice: the body's and a stored submission's alike (P39a)."""
    if not (isinstance(key, str) and key.isdecimal()):
        raise _bad("rabbits", "Ange kaninerna med sitt id.")
    raw = _keys(raw, ENTRY_KEYS, "rabbits")
    val, hull = raw.get("val"), raw.get("hull")
    if val is None:
        return None
    if val not in CHOICES:
        raise _bad("val", "Välj Finns kvar, Död eller slaktad eller Såld.")
    if hull not in (None, "low", "normal", "high"):
        raise _bad("hull", "Hullet är mager, normal eller fet.")
    dod = sald = None  # the details of another choice are left behind
    if val == "dod":
        dod = _month(raw.get("dod"), "dod", ("slaktad", "anteckning"))
        slaktad = raw["dod"].get("slaktad", False)
        if not isinstance(slaktad, bool):
            raise _bad("dod", "Slaktad är ja eller nej.")
        dod |= {"slaktad": slaktad, "anteckning": _text(raw["dod"].get("anteckning"), "anteckning")}
    if val == "sald":
        sald = _month(raw.get("sald"), "sald", ("till", "kopare"))
        till, kopare = raw["sald"].get("till"), raw["sald"].get("kopare")
        if not isinstance(till, str) or not till:
            raise _bad("sald", "Ange köparens besättning, eller utanför genbanken.")
        if kopare is not None and (till != "utanfor" or not isinstance(kopare, dict)):
            raise _bad("kopare", "Köparens namn och ort anges bara vid försäljning utanför genbanken.")
        sald = {"till": till, **sald, "kopare": kopare}
    return RabbitEntry(int(key), val, _vikt(raw.get("vikt")), _text(raw.get("ej_vagd"), "ej_vagd"), hull, dod, sald)


def _entries(rabbits):
    if not isinstance(rabbits, dict):
        raise _bad("rabbits", "Fältet ska vara ett objekt.")
    entries = (_entry(key, raw) for key, raw in rabbits.items())
    return {entry.individual_id: entry for entry in entries if entry is not None}


def _diseases(value):
    diseases = {}
    for name, raw in _keys(value or {}, DISEASES, "diseases").items():
        raw = _keys(raw, ("namn", "antal", "alder") if name == "annat" else ("antal", "alder"), "diseases")
        antal = raw.get("antal")
        if not (_is_int(antal) and 0 <= antal <= 1000):
            raise _bad("antal", "Ange antalet som ett heltal från 0 till 1000.")
        diseases[name] = {"antal": antal, "alder": _text(raw.get("alder"), "alder")}
        if name == "annat":
            diseases[name] = {"namn": _text(raw.get("namn"), "annat.namn"), **diseases[name]}
    return diseases


def _defects(value):
    if not isinstance(value or [], list):
        raise _bad("defects", "Defekterna ska vara en lista.")
    defects = []
    for raw in value or []:
        raw = _keys(raw, ("individual_id", "beskrivning", "foto"), "defects")
        if not _is_int(raw.get("individual_id")) or raw.get("foto") is not None:  # D16: photos come in step 4
            raise _bad("defects", "Ange kaninen med sitt id, utan foto.")
        beskrivning = _text(raw.get("beskrivning"), "beskrivning")
        defects.append({"individual_id": raw["individual_id"], "beskrivning": beskrivning, "foto": None})
    return defects


def _day(value, field_):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise _bad(field_, "Ange datumet som ÅÅÅÅ-MM-DD.") from exc


def _paper(body):
    item_id = body.get("inbox_item_id")
    if not _is_int(item_id):
        raise _bad("inbox_item_id", "Ange posten som ett nummer.")
    received = _day(body.get("received_on"), "received_on")  # P40: required, the client always sends it
    signed = _day(body["signed_on"], "signed_on") if body.get("signed_on") is not None else received
    if signed > received:
        raise _bad("signed_on", "Blankettens datum kan inte vara senare än dagen den kom in.")
    if body.get("matrikel") is not None and not isinstance(body["matrikel"], dict):
        raise _bad("matrikel", "Fältet ska vara ett objekt.")
    return {"inbox_item_id": item_id, "received_on": received, "signed_on": signed, "matrikel": body.get("matrikel")}


def parse_submission(body: dict, *, paper: bool) -> Submission:
    """
    The submission body, or a 400 that names the field. It reads neither the database nor the clock, so equal
    bodies parse equal (D21). Free text passes reject_contact_details here, so that require_reason at write time
    never turns it into a 422 on some rabbit.
    """
    _keys(body, BODY_KEYS + (PAPER_KEYS if paper else ()), "body")
    try:
        key = uuid.UUID(body["submission_key"]) if body.get("submission_key") is not None else None
    except (AttributeError, TypeError, ValueError) as exc:
        raise _bad("submission_key", "Ange submission_key som ett UUID.") from exc
    revision = body.get("revision")
    if revision is not None and not _is_int(revision):
        raise _bad("revision", "Ange revisionen som ett heltal.")
    ending, membership, health = (body.get(k) for k in ("ending_genbank", "membership_after_end", "health"))
    if ending is not None and not isinstance(ending, bool):
        raise _bad("ending_genbank", "Fältet är ja eller nej.")
    if membership not in (None, "kvar_utan_genbank", "avsluta_medlemskap"):
        raise _bad("membership_after_end", "Välj vad som händer med medlemskapet.")
    if health not in (None, "inga", "ja"):
        raise _bad("health", "Välj Inga sjukdomsfall eller defekter, eller Ja.")
    rabbits = _entries(body.get("rabbits") or {})
    report = {
        "ending_genbank": bool(ending),
        "membership_after_end": membership,
        "not_weighed": {str(rabbit): entry.ej_vagd for rabbit, entry in rabbits.items() if entry.ej_vagd},
        "health": health,
        "diseases": _diseases(body.get("diseases")),
        "defects": _defects(body.get("defects")),
        "not_stated": sorted(rabbit for rabbit, entry in rabbits.items() if entry.val == "ej_angiven"),
        "message": _text(body.get("message"), "message") or "",
    }
    reason = _text(body.get("reason"), "reason")
    return Submission(key, revision, reason, rabbits, report, _paper(body) if paper else None)


def partial_date(ar, manad, dag, on: date) -> date:
    """A death's or a sale's date (5.3): without the day, the month's last day, or `on` when that is earlier."""
    if dag is not None:
        return date(ar, manad, dag)
    return min(date(ar, manad, calendar.monthrange(ar, manad)[1]), on)


# The effects on the register: what a submission wants, what the report wrote, and the difference (5.4, 8, D5)

RANK = {"death": 0, "transfer": 0, "weight": 1, "bodyfat": 1, "attest": 2}
ROW_KINDS = ("attest", "transfer")  # the effects that are herd-tracking rows


@dataclass(frozen=True)
class Effect:
    kind: str  # attest | death | transfer | weight | bodyfat
    date: date
    value: tuple  # attest (); death (death_date, butchered, note); transfer (herd_code,); weight (kg,); bodyfat (lvl,)
    ref: object = field(default=None, compare=False)  # current effects: ht id, operation id or measurement row id


def order(e: Effect, last: date) -> tuple:
    """
    The write order (5.4 point 3): by date, and on one day deaths and sales, then measurements, then the
    attestation. A rabbit's effects up to `last` thus come before those after it.
    """
    return (e.date, RANK[e.kind])


def _holder_on(individual_id, day, ops):
    """The herd holding the rabbit on `day` by its active rows outside `ops` (D3b), else its origin herd."""
    rows = (
        HerdTracking.select(HerdTracking.herd, HerdTracking.operation_id)
        .where(HerdTracking.individual == individual_id, ht_not_voided(), HerdTracking.herd_tracking_date <= day)
        .order_by(*ht_order_desc())
    )
    holder = next((row.herd_id for row in rows if str(row.operation_id) not in ops), None)
    return holder or Individual.select(Individual.origin_herd).where(Individual.id == individual_id).scalar()


def _registered_death(individual_id, ops):
    """The register has a death date the report did not write: RecordDeath never overwrites it with a month."""
    died = Individual.select(Individual.death_date).where(Individual.id == individual_id).scalar()
    return died is not None and str(latest_death_op(individual_id)) not in ops


def _sale_code(herd, till):
    """The buyer's herd code: "utanfor" is the genebank's GX1 or MX1."""
    if till != "utanfor":
        return till
    outside = Herd.select(Herd.herd).where(Herd.genebank == herd.genebank_id, Herd.herd.in_(OUTSIDE_GENEBANK_HERDS))
    return outside.scalar()


def wanted(entry, rabbit_row, report, herd, year, on) -> list[Effect]:
    """
    The effects `entry` asks of the register (5.4 point 3); `rabbit_row` is the rabbit's report_list row, whose
    state already leaves the report's own rows out (D3b), as the holder here does. The buyer is not part of a
    transfer's value: the write passes kopare along.
    """
    last, ops = date(year, 12, 31), report_ops(report) if report is not None else set()
    rabbit, dod, sald = entry.individual_id, entry.dod, entry.sald
    if entry.val == "ej_angiven":
        return []
    died = dod and partial_date(dod["ar"], dod["manad"], dod["dag"], on)
    sold = sald and partial_date(sald["ar"], sald["manad"], sald["dag"], on)
    effects = []
    if not ((died and died <= last) or (sold and sold <= last)):  # it lived on 31/12: what kvar gives
        if rabbit_row["state"] == "att_valja" and _holder_on(rabbit, last, ops) == herd.id:
            effects.append(Effect("attest", last, ()))
        if entry.vikt is not None:
            effects.append(Effect("weight", last, (round(entry.vikt, 2),)))
        if entry.hull is not None:
            effects.append(Effect("bodyfat", last, (entry.hull,)))
    if died and not _registered_death(rabbit, ops):
        effects.append(Effect("death", died, (died, dod["slaktad"], dod["anteckning"])))
    if sold:
        effects.append(Effect("transfer", sold, (_sale_code(herd, sald["till"]),)))
    return effects


def current(report, individual_id) -> list[Effect]:
    """The effects the report's submissions wrote on the rabbit that are still in the register, with refs."""
    if report is None:
        return []
    submissions = _submissions(report)
    ops = {str(op) for submission in submissions for op in submission.operation_ids}
    rows = (
        HerdTracking.select(HerdTracking, Herd)
        .join(Herd, on=(HerdTracking.herd == Herd.id))
        .where(
            HerdTracking.individual == individual_id,
            ht_not_voided(),
            ((HerdTracking.kind == "ATTESTATION") & (HerdTracking.yearly_herd_report == report.id))
            | (HerdTracking.kind == "TRANSFER"),
        )
    )
    effects = []
    for row in rows:
        day = coerce_date(row.herd_tracking_date)
        if row.kind == "ATTESTATION":
            effects.append(Effect("attest", day, (), ref=row.id))
        elif str(row.operation_id) in ops:
            effects.append(Effect("transfer", day, (row.herd.herd,), ref=row.id))
    undone = IndividualCommand.select(IndividualCommand.undoes).where(
        IndividualCommand.individual == individual_id, IndividualCommand.undoes.is_null(False)
    )
    deaths = IndividualCommand.select(IndividualCommand.operation_id, IndividualCommand.after).where(
        IndividualCommand.individual == individual_id,
        IndividualCommand.command == "RecordDeath",
        IndividualCommand.operation_id.not_in(undone),
    )
    rabbit = None
    for command in (command for command in deaths if str(command.operation_id) in ops):
        rabbit = rabbit or Individual.get_by_id(individual_id)
        stored = {"death_date": _iso(rabbit.death_date), "butchered": rabbit.butchered, "death_note": rabbit.death_note}
        # Undo's own test: an editor replaced or cleared the death on the rabbit page, so it is no longer there
        if any(stored.get(key) != value for key, value in (command.after or {}).items()):
            continue
        if stored["death_date"] is not None:  # P39b: the log has the changed columns only, the rabbit has them all
            day = coerce_date(stored["death_date"])
            value = (day, bool(stored["butchered"]), stored["death_note"] or None)
            effects.append(Effect("death", day, value, ref=command.operation_id))
    added = [m for submission in submissions for m in submission.added_measurements]
    listed = [m for m in added if m["individual_id"] == individual_id]
    ids = {kind: [m["id"] for m in listed if m["kind"] == kind] for kind in ("weight", "bodyfat")}
    effects += [
        Effect("weight", coerce_date(row.weight_date), (round(row.weight, 2),), ref=row.id)
        for row in Weight.select().where(Weight.id.in_(ids["weight"]))
    ]
    effects += [
        Effect("bodyfat", coerce_date(row.bodyfat_date), (row.bodyfat,), ref=row.id)
        for row in Bodyfat.select().where(Bodyfat.id.in_(ids["bodyfat"]))
    ]
    return effects


def same_sale(a, b) -> bool:
    """The same sale as given (buyer herd and date); a buyer given again is a correction of it, not another sale."""
    return bool(a and b) and all(a[key] == b[key] for key in ("till", "ar", "manad", "dag"))


def diff(cur, want, last, prev_entry=None, entry=None) -> tuple[list[Effect], list[Effect]]:
    """
    (remove, add): what a change voids, undoes or deletes, and what it writes, given the rabbit's entry in the
    latest submission as `prev_entry` (always with `entry`). Pure. Once a row goes, every later one comes off too,
    so that each void hits the latest row, and the wanted ones from there on are written again.
    """
    if prev_entry and prev_entry.dod == entry.dod:  # same raw input: do not re-resolve the death date
        want = [next((c for c in cur if c.kind == "death"), w) if w.kind == "death" else w for w in want]
    fixed = bool(entry and entry.sald and entry.sald.get("kopare"))  # a buyer given again corrects it (Codex 8)
    if prev_entry and same_sale(prev_entry.sald, entry.sald):  # a correction keeps the date
        want = [next((c for c in cur if c.kind == "transfer"), w) if w.kind == "transfer" else w for w in want]

    def rows(effects):
        return [e for e in effects if e.kind in ("attest", "death", "transfer")]

    gone = [c for c in rows(cur) if c not in want or (fixed and c.kind == "transfer")]
    cut = min((order(c, last) for c in gone), default=None)
    remove = [c for c in rows(cur) if cut is not None and order(c, last) >= cut]
    add = [w for w in rows(want) if w not in cur or (cut is not None and order(w, last) >= cut)]
    remove += [c for c in cur if c.kind in ("weight", "bodyfat") and c not in want]
    add += [w for w in want if w.kind in ("weight", "bodyfat") and w not in cur]
    return remove, add


# The dry run (5.4 point 1)


@dataclass(frozen=True)
class Refusal:
    individual_id: int | None
    code: str
    message: str


REFUSALS = {  # the copy the client shows (P44)
    "inte_klar": "Välj Finns kvar, Död eller slaktad eller Såld.",
    "vikt_saknas": "Vuxna kaniner behöver vikt eller Ej vägd.",
    "vikt_ogiltig": "Ange vikten i kilo, till exempel 2,8.",
    "ej_angiven_digitalt": "Ej angiven finns bara när en blankett matas in.",
    "forsaljning_skotare": "Försäljningen registreras av ägaren eller genbanksansvarig.",
    "kopare_saknas": "Skriv köparens namn och ort.",
    "senare_handelse": "Kaninen har en senare händelse i Stamboken. Genbanksansvarig kan rätta.",
    "okand_kanin": "Kaninen finns inte i listan för besättningen.",
    "halsa_saknas": "Välj Inga sjukdomsfall eller defekter, eller Ja.",
    "orsak_kravs": "Skriv varför rapporten ändras.",
    "rundan_stangd": "Rundan är stängd.",
}
# _validate_sale's user: the report never sells into another genebank, since TransferIndividual needs a reason there.
_NOT_ADMIN = SimpleNamespace(is_admin=False)


def _refusal(individual_id, code, message=None):
    return Refusal(individual_id, code, message or REFUSALS[code])


def _sale_view(individual_id, kept):
    """_validate_sale's view of the rabbit on the rows `kept` (P38: built here, as as_dict needs a litter)."""
    rabbit = Individual.get_by_id(individual_id)
    holder = kept[-1].herd if kept else rabbit.origin_herd
    return {
        "herd": holder.herd,
        "genebank_id": holder.genebank_id,
        "is_registered": bool(rabbit.certificate or rabbit.digital_certificate),
        "birth_date": _iso(rabbit.breeding.birth_date) if rabbit.breeding_id else None,
        "herd_tracking": [{"date": _iso(coerce_date(row.herd_tracking_date))} for row in kept],
    }


def _register_refusals(individual_id, entry, remove, add):
    """
    What the writes would meet in the register: a void that is not the latest row (report_void_denial) or a row
    behind a later one (DATE_BEFORE_LATEST), then each new sale under _validate_sale and the buyer rules.
    """
    if not any(e.kind in ROW_KINDS for e in remove + add):
        return []
    rows = list(
        HerdTracking.select(HerdTracking, Herd)
        .join(Herd, on=(HerdTracking.herd == Herd.id))
        .where(HerdTracking.individual == individual_id, ht_not_voided())
    )
    gone = {e.ref for e in remove if e.kind in ROW_KINDS}
    kept = sorted((row for row in rows if row.id not in gone), key=ht_sort_key)
    if kept and (
        any(ht_sort_key(row) < ht_sort_key(kept[-1]) for row in rows if row.id in gone)
        or any(e.date < coerce_date(kept[-1].herd_tracking_date) for e in add if e.kind in ROW_KINDS)
    ):
        return [_refusal(individual_id, "senare_handelse")]
    from blueprints.individuals import _validate_sale  # pylint: disable=import-outside-toplevel  # it imports utils

    refusals = []
    for sale in (e for e in add if e.kind == "transfer"):
        kopare, form = entry.sald["kopare"], {"selling_date": sale.date.isoformat(), "herd": sale.value[0]}
        if error := _validate_sale(_sale_view(individual_id, kept), form, _NOT_ADMIN, kopare):
            refusals.append(_refusal(individual_id, "forsaljning", error.replace("Försäljningsdatumet", "Säljdatumet")))
        if sale.value[0] in OUTSIDE_GENEBANK_HERDS and kopare is None:
            refusals.append(_refusal(individual_id, "kopare_saknas"))
        elif sale.value[0] in OUTSIDE_GENEBANK_HERDS:
            try:
                buyer_contact_fields(kopare)
            except HerdTrackingInvalid as exc:
                refusals.append(_refusal(individual_id, "kopare", str(exc)))
    return refusals


def check(herd, round_, access, report, sub, *, on: date) -> tuple[list[Refusal], list[Refusal]]:
    """
    The dry run (5.4 point 1): (refusals, warnings) for the submission `sub` on the herd's current `report`, as of
    `on`. It takes no lock and writes nothing; Skicka runs it again under the locks.
    """
    year, end = round_.report_year, round_.end_date
    last, late = date(year, 12, 31), end is not None and on > end
    # D11, P39c: after end_date an editor, and a helper's first entry, both with a reason
    late_ok = (
        late
        and round_open(round_, herd.genebank_id, end)
        and (access.editor or (access.role == "helper" and report is None))
    )
    if not (round_open(round_, herd.genebank_id, on) or late_ok):
        return [_refusal(None, "rundan_stangd")], []
    submissions = _submissions(report) if report is not None else []
    latest = submissions[-1].data if submissions else None
    before_entries = _entries(latest.get("rabbits") or {}) if latest else {}
    refusals, warnings = [], []
    if not sub.reason and (
        (access.source == "paper" and report is not None) or (late and (access.editor or access.role == "helper"))
    ):
        refusals.append(_refusal(None, "orsak_kravs"))
    # A null in the latest submission came from paper, or an editor kept it there (case 8 by phone).
    kept_null = access.editor and latest is not None and latest.get("health") is None
    if access.source != "paper" and sub.report["health"] is None and not kept_null:
        refusals.append(_refusal(None, "halsa_saknas"))
    rows = {row["id"]: row for row in report_list(herd, year, report)}
    strangers = [rabbit for rabbit in sub.rabbits if rabbit not in rows]
    strangers += [d["individual_id"] for d in sub.report["defects"] if d["individual_id"] not in rows]
    refusals += [_refusal(rabbit, "okand_kanin") for rabbit in strangers]
    for rabbit, row in rows.items():
        entry, before = sub.rabbits.get(rabbit), before_entries.get(rabbit)
        if entry is None:
            if row["state"] == "att_valja":
                refusals.append(_refusal(rabbit, "inte_klar"))
            continue
        kept = access.editor and before is not None and before.val == "ej_angiven"
        if entry.val == "ej_angiven" and access.source != "paper" and not kept:
            refusals.append(_refusal(rabbit, "ej_angiven_digitalt"))
            continue
        if entry == before:  # P39a: an unchanged choice writes nothing and is not refused
            continue
        if row["state"] != "att_valja":
            refusals.append(_refusal(rabbit, "senare_handelse"))
            continue
        if entry.val == "ej_angiven":
            continue
        if entry.val == "sald" and not access.can_sell:
            refusals.append(_refusal(rabbit, "forsaljning_skotare"))
            continue
        if entry.vikt is not None and not 0 < entry.vikt <= 20:
            refusals.append(_refusal(rabbit, "vikt_ogiltig"))
        elif entry.vikt is not None and not 1.0 <= entry.vikt <= 6.5:
            warnings.append(Refusal(rabbit, "vikt_ovanlig", f"Stämmer {format(entry.vikt, 'g').replace('.', ',')} kg?"))
        if (
            entry.val == "kvar"
            and row["adult"]
            and entry.vikt is None
            and not entry.ej_vagd
            and not sub.report["ending_genbank"]
        ):
            refusals.append(_refusal(rabbit, "vikt_saknas"))
        remove, add = diff(current(report, rabbit), wanted(entry, row, report, herd, year, on), last, before, entry)
        refusals += _register_refusals(rabbit, entry, remove, add)
    return refusals, warnings
