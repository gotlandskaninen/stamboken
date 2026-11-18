"""
The yearly report v2 (årsrapport): rounds, their activation per genebank, who may report for a herd, the herd's
list (5.2), the report view, the server draft, the submission and its effects on the register, the dry run,
Ändra and Dra tillbaka.
The routes are in blueprints/arsrapport.py (ADR-0007).
"""

import calendar
import hashlib
import hmac
import json
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import current_app
from peewee import JOIN, IntegrityError, fn

import utils.inbox as inbox
import utils.report_code as report_code
from utils.arsrapport_statistik import SEXES, Kanin, innehav, statistik
from utils.data_access import MAX_GESTATION_DAYS
from utils.database import (
    DB_PROXY,
    LIFE_SIGN_KINDS,
    OUTSIDE_GENEBANK_HERDS,
    AuditLog,
    Bodyfat,
    Breeding,
    BuyerContact,
    Color,
    Herd,
    HerdTracking,
    InboxDocument,
    InboxEvent,
    InboxItem,
    Individual,
    IndividualCommand,
    MailMessage,
    MatrikelAudit,
    Member,
    MemberChangeRequest,
    Membership,
    PublicationConsentChange,
    ReportAccessCode,
    SaleProposal,
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
    lock_breedings,
    lock_individuals,
    not_voided,
)
from utils.database import (
    account_end as masked_account,
)
from utils.herd_tracking import (
    DATE_BEFORE_LATEST,
    QUEUE_CHANGED,
    REPORT_LATER_ROW,
    HerdTrackingError,
    HerdTrackingInvalid,
    QueueChanged,
    _reject_buyer_name,
    buyer_contact_fields,
    buyer_items,
    drop_kept_buyers,
    latest_death_op,
    reject_contact_details,
    report_void_denial,
    void_herd_tracking,
)
from utils.individual_commands import (
    LITTER_CHANGED,
    REPORT_UNDO_REASON,
    IndividualRefused,
    RecordAttestation,
    RecordDeath,
    SameLitter,
    SetMeasurements,
    TransferIndividual,
    Undo,
    confirm_litter_size,
    execute,
    register_litter,
)
from utils.individual_policy import Role
from utils.mail import Recipient, enqueue_mail, mail_kind, recipient_kind
from utils.matrikel import AddressValidationError, is_anonymized, parse_postal_fields, write_matrikel_audit
from utils.members import CONSENT_TEXT_VERSION, consent_from_answer, effective_consent, set_consent, stored_consent
from utils.reference_population import _alive_by_note
from utils.report_code import actor_key

STOCKHOLM = ZoneInfo("Europe/Stockholm")
BLANK_FORM = "arsrapport/arsblankett.pdf"  # under settings.service.private_upload_folder (D14)
STATES = ("avslutar", "inskickad", "blankett_vantar", "blankett_inkommen", "paborjad", "ingen_epost", "ej_rapporterad")
DATE_FIELDS = ("start_date", "deadline", "end_date")
DRAFT_MAX_BYTES = 256 * 1024
LINK_INVALID = "Länken gäller inte längre."
WITHDRAW_DAYS = 7  # fråga 15: owners and caretakers withdraw until 7 days after the first submission
_REPORT_LOCK = 0x48424152  # "HBAR": classid of the advisory lock on a herd's report in a round


class ArsrapportError(Exception):
    """A refusal with its HTTP status; the blueprint turns it into problem(status, title, detail, **extra)."""

    TITLES = {
        400: "Ogiltig begäran",
        401: "Autentisering krävs",
        403: "Åtkomst nekad",
        404: "Hittades inte",
        409: "Konflikt",
        422: "Kan inte sparas",
    }

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
    sees end_date only when it moves. In one transaction: the UPDATE holds the round row until the codes and the
    kept buyers have followed it (follow_end_date), which Dra tillbaka waits for (_lock_round).
    """
    if abs(year - today().year) > 1:
        raise ArsrapportError(400, f"Året ska vara {today().year - 1}, {today().year} eller {today().year + 1}.")
    with DB_PROXY.atomic():
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
            if "end_date" in changed:
                follow_end_date(round_)
    return round_


def follow_end_date(round_):
    """
    R10: the column of the round's active codes follows its end_date, and K2: so do the kept buyers. In the caller's
    transaction, after its UPDATE of the round row, which holds the row to the commit: save_round, and legacy's
    PATCH (data_access.update_yearly_report_round). A cleared end_date (legacy only) moves neither: a code without
    one is invalid anyway (report_code.refusal), and a kept buyer keeps the purge_at it has.
    """
    if round_.end_date is None:
        return
    ReportAccessCode.update(expires_at=round_.end_date).where(
        ReportAccessCode.round == round_.id, ReportAccessCode.revoked_at.is_null()
    ).execute()
    _move_kept_buyers(round_)


def _lock_round(round_):
    """
    The round row FOR SHARE, read again: Dra tillbaka keeps a buyer until the round's end_date (kept_until), and
    save_round's UPDATE of the row waits for it. A moved end_date is then either read here or comes after the
    withdrawal, and _move_kept_buyers finds its buyer. Taken first, before the report's lock and the link's code row,
    which save_round updates after the round row. The invitation job takes it first too, before the activation row
    and the codes it issues and revokes herd by herd.
    """
    return YearlyReportRound.select().where(YearlyReportRound.id == round_.id).for_update("FOR SHARE").get()


def kept_until(round_):
    """
    K2: purge_at of a buyer kept across Dra tillbaka: the midnight in Stockholm after end_date, plus one day, so the
    nightly purge after end_date spares it and the next one takes it. None without an end_date.
    """
    if round_.end_date is None:
        return None
    day = round_.end_date + timedelta(days=2)
    return datetime(day.year, day.month, day.day, tzinfo=STOCKHOLM)


def _move_kept_buyers(round_):
    """
    K2: the kept buyers of the round's voided reports follow a changed end_date: those a TRANSFER the reports' own
    operations wrote held, now voided, and that no active row holds.
    """
    voided = YearlyHerdReport.select(YearlyHerdReport.id).where(
        YearlyHerdReport.round == round_.id, YearlyHerdReport.status == "voided"
    )
    written = YearlyReportSubmission.select(YearlyReportSubmission.operation_ids).where(
        YearlyReportSubmission.report.in_(voided)
    )
    ops = sorted({str(op) for (ops,) in written.tuples() for op in ops})
    sold = HerdTracking.select(HerdTracking.individual, HerdTracking.holder_contact).where(
        HerdTracking.kind == "TRANSFER",
        HerdTracking.voided_at.is_null(False),
        HerdTracking.operation_id.in_(ops),
        HerdTracking.holder_contact.is_null(False),
    )
    sold = list(sold.tuples())
    held = HerdTracking.select(HerdTracking.holder_contact).where(
        HerdTracking.holder_contact.is_null(False), ht_not_voided()
    )
    # The rabbits first, as a resubmission takes them all before it links their buyers in rabbit order, then the
    # buyers in id order, as the purge locks them, and `held` read after: a resubmission that linked one again has
    # committed by then, and keeps its five years
    lock_individuals({rabbit for rabbit, _ in sold})
    locked = BuyerContact.select(BuyerContact.id).where(BuyerContact.id.in_([c for _, c in sold]))
    locked = locked.order_by(BuyerContact.id)
    ids = [contact_id for (contact_id,) in locked.for_update().tuples()]
    BuyerContact.update(purge_at=kept_until(round_)).where(
        BuyerContact.id.in_(ids), BuyerContact.id.not_in(held)
    ).execute()


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
    role: str  # owner | caretaker | manager | admin | helper | code
    item: InboxItem | None = None  # paper only: the taken item with an arsblankett document
    code: ReportAccessCode | None = None  # the personal link (step 3): role "code"

    @property
    def source(self):
        return "paper" if self.item else "link" if self.code else "login"

    @property
    def can_sell(self):
        return self.role not in ("caretaker", "code")  # D12; a link's sale is a proposal (step 4)

    @property
    def editor(self):
        return self.role in ("manager", "admin")

    @property
    def reads_buyers(self):
        return self.role in ("manager", "admin", "helper")  # can_see_buyer: the herd's genebank, or admin


def _form_item(item, user, herd):
    """
    The paper path's item (5.5): the user's taken item for the herd, not decided in another feature, with an
    arsblankett document. A helper's own upload counts like any other (Jonas 2026-11-15).
    """
    return (
        item.herd_id == herd.id
        and item.state == "tagen"
        and item.assigned_to_id == user.id
        and item.ref_type is None
        and item.documents.where(InboxDocument.doc_type == "arsblankett").exists()
    )


def report_access(user, herd, item_id=None):
    """
    The user's right to the herd's report, or None. On paper (`item_id`) only through such an item (_form_item). It
    reads the item without a lock; Skicka checks it again under inbox.lock_item.
    """
    if herd.herd in OUTSIDE_GENEBANK_HERDS:
        return None
    managed = herd.genebank_id in (user.is_manager or ())
    if item_id is not None:
        item = InboxItem.get_or_none(InboxItem.id == item_id)
        if item is None or not _form_item(item, user, herd):
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


def code_access(herd, round_, code_ids):
    """
    The link's access: the session's valid code for this herd and round, else None. A code for the herd that is
    no longer valid (revoked, expired, a new main member) is a 403 `lank_ogiltig`, which the page shows as 5.13.
    """
    codes = list(
        ReportAccessCode.select().where(
            ReportAccessCode.id.in_(code_ids), ReportAccessCode.herd == herd.id, ReportAccessCode.round == round_.id
        )
    )
    for code in codes:
        if report_code.refusal(code, herd, today=today()) is None:
            return Access("code", code=code)
    if codes:
        raise ArsrapportError(403, LINK_INVALID, code="lank_ogiltig")
    return None


def require_valid_code(code_id, herd, on=None, *, lock=False):
    """
    E4 on rows read afresh: 403 `lank_ogiltig` unless the code is valid for the herd. With `lock` the code row is
    read FOR SHARE and held to the end of the transaction, so a revoke (an UPDATE of that row) waits for the write
    that passed this check, and a revoke that came first is seen.
    """
    query = ReportAccessCode.select().where(ReportAccessCode.id == code_id)
    code = (query.for_update("FOR SHARE") if lock else query).get()
    if report_code.refusal(code, Herd.get_by_id(herd.id), today=on or today()) is not None:
        raise ArsrapportError(403, LINK_INVALID, code="lank_ogiltig")


def _recheck_code(access, herd, on=None):
    """E4 again, under the report's lock: the manager may have revoked the code since the page."""
    if access.code is not None:
        require_valid_code(access.code.id, herd, on, lock=True)


def without_reason(sub):
    """
    The system's reason in place of a typed one, for a role that may not read buyers (not reads_buyers): the name check
    on a typed reason would let the dry run, Skicka and Dra tillbaka probe the names of the rabbits' buyers, a kept
    one too, and a reason that is never stored never carries one.
    """
    return replace(sub, reason=None) if sub.reason else sub


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
    """
    The report's submissions, oldest first: in the order they were written, which the report's lock serializes. Not
    by created_at, which a writer takes before it waits for the lock (P1).
    """
    query = YearlyReportSubmission.select().where(YearlyReportSubmission.report == report.id)
    return list(query.order_by(YearlyReportSubmission.id))


def report_ops(report):
    """The operation ids (str) the report's submissions wrote: the report's own rows (D3b, D4)."""
    return {str(op) for submission in _submissions(report) for op in submission.operation_ids}


def dayless(data, individual_id, key):
    """
    A submission's `data` gives the rabbit's death or sale (`key` dod or sald) without its day (5.3): the register's
    date of it is made up (partial_date), so only its month is shown. False without the data.
    """
    entry = ((data or {}).get("rabbits") or {}).get(str(individual_id))
    when = entry.get(key) if isinstance(entry, dict) else None
    return isinstance(when, dict) and when.get("dag") is None


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
    31/12 in H) or "via_flytt" (an active life sign after 31/12, the first of them in `later`). `kopt` is the
    latest active TRANSFER into H dated in the year: its date and the seller herd (Task 5).
    """
    last = date(year, 12, 31)
    ids, written = _listed_5_2(herd, last), {}
    if report is not None:
        submissions = _submissions(report)
        written = {str(op): submission.data for submission in submissions for op in submission.operation_ids}
        ids |= {int(key) for key in (submissions[-1].data.get("rabbits") or {})} if submissions else set()
    ops = set(written)
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
            # a death the report wrote without its day: its month only (5.3)
            "death_day_known": death is None
            or death <= last
            or not dayless(written.get(str(latest_death_op(rabbit["id"]))), rabbit["id"], "dod"),
            "state": "att_valja",
            "later": None,
            "kopt": None,
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
    Seller = Herd.alias()
    bought = (
        HerdTracking.select(HerdTracking.individual, HerdTracking.herd_tracking_date, Seller.herd.alias("fran"))
        .join(Seller, JOIN.LEFT_OUTER, on=(HerdTracking.from_herd == Seller.id))
        .where(
            HerdTracking.individual.in_(sorted(rows)),
            HerdTracking.herd == herd.id,
            HerdTracking.kind == "TRANSFER",
            ht_not_voided(),
            HerdTracking.herd_tracking_date.between(date(year, 1, 1), last),
        )
        .order_by(HerdTracking.herd_tracking_date, HerdTracking.id)
    )
    for row in bought.dicts():  # oldest first: the latest purchase wins
        rows[row["individual"]]["kopt"] = {"datum": _iso(row["herd_tracking_date"]), "fran": row["fran"]}
    return list(rows.values())


PRIVATE_KEYS = ("matrikel", "kopare")  # never stored in a draft, at any depth under `form`


def _has_private(value):
    """A non-null matrikel or kopare anywhere inside `value` (a null is only stripped)."""
    if isinstance(value, dict):
        return any((k in PRIVATE_KEYS and v is not None) or _has_private(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_private(v) for v in value)
    return False


def _without_private(value):
    if isinstance(value, dict):
        return {k: _without_private(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [_without_private(v) for v in value]
    return value


def stored_body(body: dict) -> dict:
    """D10: the body without matrikel, every buyer (kopare), submission_key and revision; a copy, never mutated.
    The client's whole-form copy (`form`) is stripped the same way, at any depth."""
    stored = {key: value for key, value in body.items() if key not in ("matrikel", "submission_key", "revision")}
    if isinstance(body.get("rabbits"), dict):
        stored["rabbits"] = {
            key: {**entry, "sald": {k: v for k, v in entry["sald"].items() if k != "kopare"}}
            if isinstance(entry, dict) and isinstance(entry.get("sald"), dict)
            else entry
            for key, entry in body["rabbits"].items()
        }
    if "form" in body:
        stored["form"] = _without_private(body["form"])
    return stored


def _holds_private(body):
    """A matrikel or a buyer in the body or in its `form`: never stored in a draft (section 6)."""
    rabbits = body.get("rabbits")
    entries = rabbits.values() if isinstance(rabbits, dict) else ()
    return (
        body.get("matrikel") is not None
        or any(
            isinstance(entry, dict) and isinstance(entry.get("sald"), dict) and entry["sald"].get("kopare") is not None
            for entry in entries
        )
        or _has_private(body.get("form"))
    )


KEPT_KEYS = ("kopare_id", "fran_rapport")  # K1: a buyer kept across Dra tillbaka; only the server writes them


def _sale_outside(entry):
    """A body's or a form copy's entry that is a sale outside the genebank."""
    sald = entry.get("sald") if isinstance(entry, dict) else None
    return isinstance(sald, dict) and entry.get("val") == "sald" and sald.get("till") == "utanfor"


def _kept_claims(data):
    """K1: {rabbit (id as text): {"kopare_id", "fran_rapport"}} that the server wrote into a draft's body or form."""
    claims = {}
    for body in (data, data.get("form")):
        rabbits = body.get("rabbits") if isinstance(body, dict) else None
        for key, entry in rabbits.items() if isinstance(rabbits, dict) else ():
            sald = entry.get("sald") if isinstance(entry, dict) else None
            if isinstance(sald, dict) and sald.get("kopare_id") is not None:
                claims[key] = {k: sald.get(k) for k in KEPT_KEYS}
    return claims


def _with_kept(data, claims):
    """
    K1, FB6: a draft's data without any kept buyer the client sent, and with the server's `claims` on each rabbit whose
    sale outside the genebank is still there, in the body and in the form copy alike. The form decides when there is
    one, since the body leaves out a row still being filled in. Returns (data, the kept ids whose sale is gone).
    """
    judged = data["form"] if isinstance(data.get("form"), dict) else data
    rabbits = judged.get("rabbits") if isinstance(judged.get("rabbits"), dict) else {}
    held = {key: claim for key, claim in claims.items() if _sale_outside(rabbits.get(key))}

    def put(body):
        if not isinstance(body.get("rabbits"), dict):
            return body
        out = {}
        for key, entry in body["rabbits"].items():
            if isinstance(entry, dict) and isinstance(entry.get("sald"), dict):
                sald = {k: v for k, v in entry["sald"].items() if k not in KEPT_KEYS}
                entry = {**entry, "sald": sald | (held.get(key, {}) if _sale_outside(entry) else {})}
            out[key] = entry
        return {**body, "rabbits": out}

    data = put(data)
    data = {**data, "form": put(data["form"])} if isinstance(data.get("form"), dict) else data
    return data, {c["kopare_id"] for c in claims.values()} - {c["kopare_id"] for c in held.values()}


def _draft(herd, round_):
    return YearlyReportDraft.get_or_none((YearlyReportDraft.herd == herd.id) & (YearlyReportDraft.round == round_.id))


def _by(actor, user_field, code_field):
    """The columns that name who wrote: the account, or the link (step 3), never both."""
    code_id = getattr(actor, "access_code_id", None)
    return {user_field: None if code_id is not None else actor.id, code_field: code_id}


def draft_json(draft, user):
    """ReportView.draft; `own` says whether the asking user or link saved it last (P59b); user and code never match."""
    return {
        "data": draft.data,
        "updated_at": _iso(draft.updated_at),
        "submission_key": str(draft.submission_key) if draft.submission_key else None,
        "own": ("code", draft.updated_by_access_code_id) == actor_key(user)
        if draft.updated_by_access_code_id is not None
        else ("user", draft.updated_by_user_id) == actor_key(user),
    }


def require_open(round_, herd, access, day):
    """
    D11, P39c: the report is written on `day` only while the round is open, or after end_date by an editor or a
    helper on paper; otherwise a 409 with code rundan_stangd.
    """
    end = round_.end_date
    late_ok = access.editor or access.role == "helper"  # a helper's access always comes through the post
    # round_open on end_date itself: the genebank has activated the round and its dates are set
    late = late_ok and end is not None and day > end and round_open(round_, herd.genebank_id, end)
    if not (round_open(round_, herd.genebank_id, day) or late):
        raise ArsrapportError(409, "Rundan är inte öppen.", code="rundan_stangd")


def save_draft(herd, round_, access, user, data, updated_at, submission_key, revision):
    """
    The herd's server draft (5.1), saved under the report's lock. `updated_at` is the version the client saw (None
    for a first save) and `revision` the report revision it started from (None when it saw no report). A first save
    needs the submitted report's revision, so a late autosave after Skicka is refused (5.13); a stale version is a
    409 that carries the current draft. Only while the round is open, or after end_date for an editor or a helper on
    paper (D11, P39c); otherwise a 409 with code rundan_stangd. A kept buyer's id is the server's alone (K1): the
    client's is dropped, the stored one stays on a sale still outside the genebank, and goes with a cleared one.
    """
    day = today()
    require_open(round_, herd, access, day)
    if not isinstance(data, dict):
        raise ArsrapportError(400, "Utkastet ska vara ett objekt.")
    if "form" in data and not isinstance(data["form"], dict):
        raise ArsrapportError(400, "Utkastets formulärkopia ska vara ett objekt.")
    if _holds_private(data):
        raise ArsrapportError(400, "Utkastet sparar inte dina uppgifter eller köparens uppgifter.")
    stored = stored_body(data)
    if len(json.dumps(stored, ensure_ascii=False).encode()) > DRAFT_MAX_BYTES:
        raise ArsrapportError(400, "Utkastet är för stort.")
    with DB_PROXY.atomic():
        round_ = _lock_round(round_)  # first, as Skicka: a round closed meanwhile is read here
        require_open(round_, herd, access, day)
        lock_report(round_, herd)
        _recheck_code(access, herd, day)
        draft = _draft(herd, round_)
        report = current_report(herd, round_)
        stored, gone = _with_kept(stored, _kept_claims(draft.data) if draft is not None else {})
        if draft is None and updated_at is None and revision == (report.revision if report else None):
            try:
                with DB_PROXY.atomic():  # a savepoint: a racing first save leaves the transaction usable
                    return YearlyReportDraft.create(
                        herd=herd.id,
                        round=round_.id,
                        data=stored,
                        submission_key=submission_key,
                        updated_at=now().astimezone(timezone.utc),
                        **_by(user, "updated_by_user", "updated_by_access_code"),
                    )
            except IntegrityError:
                draft = _draft(herd, round_)
        elif draft is not None and draft.updated_at == updated_at:
            # The version always moves on, also when the clock does not.
            draft.updated_at = max(now(), draft.updated_at + timedelta(microseconds=1)).astimezone(timezone.utc)
            draft.data, draft.submission_key = stored, submission_key
            for field, value in _by(user, "updated_by_user", "updated_by_access_code").items():
                setattr(draft, field, value)
            draft.save()
            try:
                drop_kept_buyers(gone, user, lock=True)  # FB6: a cleared sale takes its kept buyer now
            except QueueChanged as exc:
                raise ArsrapportError(409, QUEUE_CHANGED) from exc
            return draft
        if report is not None and draft is None:
            raise ArsrapportError(409, "Rapporten är redan inskickad.", draft=None)
        raise ArsrapportError(
            409, "Rapporten har ändrats på en annan enhet.", draft=draft_json(draft, user) if draft else None
        )


def _on_time(report, deadline):
    if report.on_time_override is not None:
        return report.on_time_override
    received = report.received_at
    return bool(received and deadline and received.astimezone(STOCKHOLM).date() <= deadline)


def on_time(report, round_):
    """i_tid: the manager's override if set, else the Stockholm date of received_at on or before the deadline."""
    return _on_time(report, round_.deadline)


def set_on_time(report, user, value):
    """
    The manager's "i tid" override (True, False, or None for the date's own answer), under Skicka's advisory lock;
    received_at is never touched, so the override holds after a later change (case 5). Returns the fresh row.
    """
    with DB_PROXY.atomic():
        lock_report(report.round, report.herd)
        report = YearlyHerdReport.get_or_none(
            (YearlyHerdReport.id == report.id) & (YearlyHerdReport.status == "submitted")
        )
        if report is None:
            raise ArsrapportError(409, "Rapporten har ändrats.")
        report.on_time_override, report.on_time_set_by = value, user.id
        report.save(only=[YearlyHerdReport.on_time_override, YearlyHerdReport.on_time_set_by])
    return report


def support_conditions(held, stat, report, deadline):
    """
    The four support conditions of one herd (spec 8): an uncastrated male and female among `held` (the herd's
    `innehav` rows), a litter with a kit born (`stat`), and the report in time. Castrated rabbits do not count.
    """
    breeders = {kanin.sex for kanin in held if not kanin.kastrerad}
    return {
        "hane": "male" in breeders,
        "hona": "female" in breeders,
        "kull": stat is not None and stat.kullar_med_ungar >= 1,
        "i_tid": report is not None and _on_time(report, deadline),
    }


def _pending_sales(last):
    """The rabbits with a pending sale proposal dated on or before `last`: they are no holding for the support."""
    query = SaleProposal.select(SaleProposal.individual).where(
        SaleProposal.state == "foreslagen", SaleProposal.sale_date <= last
    )
    return {proposal.individual_id for proposal in query}


def herd_conditions(herd, round_, report):
    """One herd's villkor: the same rule as the status view, read from the genebank's `innehav` and `statistik`."""
    year, genebank_id = round_.report_year, herd.genebank_id
    pending = _pending_sales(date(year, 12, 31))
    held = [kanin for kanin in innehav(genebank_id, year).get(herd.id, []) if kanin.individual_id not in pending]
    return support_conditions(held, statistik(genebank_id, year).get(herd.id), report, round_.deadline)


def withdraw_until(report, access):
    """
    An owner's, caretaker's or link's last instant for Dra tillbaka: the round's first submission (received_at, which a
    report after a withdrawal inherits) + 7 days, so withdrawing and sending again never restarts it; None for the
    others.
    """
    if access.role not in ("owner", "caretaker", "code"):
        return None
    return report.received_at + timedelta(days=WITHDRAW_DAYS)


def _report_json(report, round_, access, is_open):
    submissions = _submissions(report)
    until = withdraw_until(report, access)
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
        # fråga 16, P39c: after end_date only an editor changes the report; the others read it
        "can_change": is_open or access.editor,
        "can_withdraw": can_withdraw,
        "withdraw_until": _iso(until),
    }


def account_end(herd):
    """The stored account's last two digits ("12"): the only account data paper entry reads (fråga 34)."""
    return (masked_account(herd.bank_account_number) or "").removeprefix("••") or None


def report_litters(herd, year):
    """ReportView.litters: the herd's litters born in `year`; `preliminary` while the 6-week count is a guess."""
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
            Breeding.litter_size6w_preliminary.alias("preliminary"),
        )
        .join(Mother, JOIN.LEFT_OUTER, on=(Breeding.mother == Mother.id))
        .switch(Breeding)
        .join(Father, JOIN.LEFT_OUTER, on=(Breeding.father == Father.id))
        .where(Breeding.breeding_herd_id == herd.id, Breeding.birth_date.between(date(year, 1, 1), date(year, 12, 31)))
        .order_by(Breeding.birth_date, Breeding.id)
    )
    return [{**row, "birth_date": _iso(row["birth_date"])} for row in litters.dicts()]


def buyer_herds(herd):
    """
    The sale dialog's picker behind the link (4a): the active herds of `herd`'s genebank, with the fields the
    logged-in owner's picker gets (individuals.genebank_herds_v2), and nothing more.
    """
    active = Herd.is_active == True  # noqa: E712
    rows = Herd.select().where(Herd.genebank == herd.genebank_id, active).order_by(Herd.herd)
    return [{"herd": row.herd, "herd_name": row.herd_name, "is_active": True} for row in rows]


def _forslag_json(report):
    """ReportView.forslag (5.9): the report's sale proposals not taken back, without the buyer."""
    if report is None:
        return []
    query = (
        SaleProposal.select(
            SaleProposal.individual.alias("individual_id"),
            Herd.herd.alias("to_herd"),
            SaleProposal.sale_date,
            SaleProposal.state,
        )
        .join(Herd, JOIN.LEFT_OUTER, on=(SaleProposal.to_herd == Herd.id))
        .where(SaleProposal.report == report.id, SaleProposal.state != "atertagen")
        .order_by(SaleProposal.id)
    )
    return [{**row, "sale_date": _iso(row["sale_date"])} for row in query.dicts()]


def report_view(herd, round_, access, user):
    """ReportView for the herd and the round's year, as `access` sees it ."""
    import utils.purchase_notice as purchase_notice  # pylint: disable=import-outside-toplevel  # it imports this module

    year = round_.report_year
    first, last = date(year, 1, 1), date(year, 12, 31)
    activated = _activations(round_).where(YearlyReportRoundGenebank.genebank == herd.genebank_id).exists()
    is_open = round_open(round_, herd.genebank_id, today())
    report = current_report(herd, round_)
    draft = _draft(herd, round_)
    ToHerd = Herd.alias()
    # shortcut: a sale is found by from_herd, which older rows may lack; read the holder before it if they matter.
    sales = (
        HerdTracking.select(
            HerdTracking.id,
            HerdTracking.operation_id,
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
        "litters": report_litters(herd, year),
        "sales": _sales_json(report, sales.dicts()),
        "forslag": _forslag_json(report),
        "kopanmalningar": purchase_notice.report_notices(herd, round_, access),  # closes the registered ones first
        "arenden": purchase_notice.report_cases(herd, year),  # after the closing above (S8)
        "herds": [] if access.code else sorted(row.herd for row in others),  # a link sees no other herd
        "report": {**_report_json(report, round_, access, is_open), "villkor": herd_conditions(herd, round_, report)}
        if report
        else None,
        "draft": draft_json(draft, user) if draft else None,
        "item": {
            "id": item.id,
            "received_at": _iso(item.received_at),
            "state": item.state,
            "account_end": account_end(herd),
        }
        if item
        else None,
    }


def _sales_json(report, rows):
    """
    ReportView.sales: the sale `rows` with `day_known`, false for a sale the report gave without its day (5.3), whose
    date is made up: one a submission wrote (by its operation id) or an approved proposal's (by its row).
    """
    written, approved = {}, {}
    if report is not None:
        written = {str(op): submission.data for submission in _submissions(report) for op in submission.operation_ids}
        proposals = (
            SaleProposal.select(SaleProposal.herd_tracking_id, YearlyReportSubmission.data)
            .join(YearlyReportSubmission, on=(SaleProposal.submission == YearlyReportSubmission.id))
            .where(SaleProposal.report == report.id, SaleProposal.herd_tracking_id.is_null(False))
        )
        approved = dict(proposals.tuples())
    return [
        {
            "individual_id": row["individual_id"],
            "number": row["number"],
            "to_herd": row["to_herd"],
            "date": _iso(row["date"]),
            "day_known": not dayless(
                written.get(str(row["operation_id"])) or approved.get(row["id"]), row["individual_id"], "sald"
            ),
        }
        for row in rows
    ]


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


def _row_states(herds, round_):
    """Each herd's item, draft and e-mail facts in one query apiece, for status_view's state."""
    ids = [herd.id for herd in herds]
    form = InboxDocument.select(InboxDocument.item).where(InboxDocument.doc_type == "arsblankett")
    items = {}
    for item in (
        InboxItem.select(InboxItem.id, InboxItem.herd, InboxItem.state)
        .where(InboxItem.herd.in_(ids), InboxItem.state.in_(inbox.OPEN_STATES), InboxItem.id.in_(form))
        .order_by(InboxItem.id)
    ):
        kept = items.get(item.herd_id)
        if kept is None or (item.state == "vantar_uppfodare" and kept.state != "vantar_uppfodare"):
            items[item.herd_id] = item
    drafts = {
        draft.herd_id
        for draft in YearlyReportDraft.select(YearlyReportDraft.herd).where(
            YearlyReportDraft.round == round_.id, YearlyReportDraft.herd.in_(ids)
        )
    }
    emails = {}
    holders = (
        Member.select(Herd.id.alias("herd_id"), Member.email)
        .join(Herd, on=(Herd.membership == Member.membership))
        .where(Herd.id.in_(ids), Member.role == "huvudmedlem", Member.end_date.is_null(True))
        .order_by(Member.id)
    )
    for row in holders.dicts():  # the first main member, as inbox.herd_holder
        emails.setdefault(row["herd_id"], row["email"])
    return items, drafts, emails


_MAIL_INVITATION = {"sent": "skickad", "bounced": "studsade", "failed": "misslyckades"}


def _invitations(herds, round_):
    """
    Each herd's invitation state from its active code: `oppnad` once the link has been opened, else the state of the
    mail that carries it (`skickad`, `studsade`, `misslyckades`); a herd with no active code or no such mail is None.
    """
    codes = {
        code.herd_id: code
        for code in ReportAccessCode.select().where(
            ReportAccessCode.round == round_.id,
            ReportAccessCode.herd.in_([herd.id for herd in herds]),
            ReportAccessCode.revoked_at.is_null(),
        )
    }
    mail = {
        row.ref_id: _MAIL_INVITATION.get(row.status)
        for row in MailMessage.select(MailMessage.ref_id, MailMessage.status)
        .where(
            MailMessage.ref_type == "access_code",
            MailMessage.ref_id.in_([code.id for code in codes.values()]),
            MailMessage.kind.in_(("arsrapport.inbjudan", "arsrapport.ny_lank")),
        )
        .order_by(MailMessage.id)  # the newest mail of a code decides
    }
    return {herd_id: "oppnad" if code.last_opened_at else mail.get(code.id) for herd_id, code in codes.items()}


def _only_with(more, counted, villkor, stat, report, deadline):
    """The four support conditions fail as counted, and hold once the rabbits `more` count too."""
    return bool(
        more and not all(villkor.values()) and all(support_conditions(counted + more, stat, report, deadline).values())
    )


def _sale_flags(round_, reports):
    """
    The status view's sale flags per herd, from the submitted `reports` (herd id -> report) in three queries: pending
    proposals (5.14), the rabbits a rejection left to choose again, which its submission stores without a choice
    (FB3), and approved sales on or before 31/12 into a herd whose report does not answer them yet (FB4,
    _answers_purchase). Each submission holds every rabbit chosen so far, and a rejection's copies the latest, so
    only the buyer's own choice for the rabbit answers it (P3).
    """
    herd_of = {report.id: herd_id for herd_id, report in reports.items()}
    open_ = list(
        SaleProposal.select(SaleProposal.report, SaleProposal.state).where(
            SaleProposal.report.in_(list(herd_of)), SaleProposal.state.in_(("foreslagen", "avvisad"))
        )
    )
    waiting = Counter(herd_of[p.report_id] for p in open_ if p.state == "foreslagen")
    approved = list(
        SaleProposal.select(
            SaleProposal.to_herd, SaleProposal.individual, SaleProposal.sale_date, SaleProposal.decided_at
        )
        .join(YearlyHerdReport)
        .where(
            YearlyHerdReport.round == round_.id,
            SaleProposal.state == "godkand",
            SaleProposal.sale_date <= date(round_.report_year, 12, 31),
            SaleProposal.to_herd.in_(list(reports)),
        )
    )
    rejected = {p.report_id for p in open_ if p.state == "avvisad"}
    wanted = sorted(rejected | {reports[p.to_herd_id].id for p in approved})
    history = {}  # report id -> [(created_at, rabbits)], in the order written
    for submission in (
        YearlyReportSubmission.select(
            YearlyReportSubmission.report, YearlyReportSubmission.data, YearlyReportSubmission.created_at
        )
        .where(YearlyReportSubmission.report.in_(wanted))
        .order_by(YearlyReportSubmission.id)
    ):
        history.setdefault(submission.report_id, []).append(
            (submission.created_at, submission.data.get("rabbits") or {})
        )
    latest = {report_id: written[-1][1] for report_id, written in history.items()}
    again = {
        herd_of[report_id]: sorted(int(k) for k, e in rabbits.items() if isinstance(e, dict) and e.get("val") is None)
        for report_id, rabbits in latest.items()
        if report_id in rejected
    }
    bought = Counter(
        p.to_herd_id for p in approved if not _answers_purchase(p, history.get(reports[p.to_herd_id].id, []))
    )
    return waiting, again, bought


def _answers_purchase(purchase, history):
    """
    FB4, Codex round 2: the buyer's report answers an approved purchase when its entry for the rabbit was last
    changed by a submission after the approval, and covers 31/12 from the purchase on: kvar, or a death or a sale on
    or after the purchase date. An older answer, such as the rabbit's own sale before it was bought back, never does.
    """
    key = str(purchase.individual_id)
    raw = history[-1][1].get(key) if history else None
    entry = _entry(key, raw) if isinstance(raw, dict) else None
    if entry is None or entry.val not in ("kvar", "dod", "sald"):
        return False
    written = history[-1][0]
    for at, rabbits in reversed(history):  # back to the submission that changed it (a rejection's copies it)
        if not isinstance(rabbits.get(key), dict) or _entry(key, rabbits[key]) != entry:
            break
        written = at
    if purchase.decided_at is not None and written <= purchase.decided_at:
        return False
    when = entry.dod or entry.sald
    return entry.val == "kvar" or partial_date(when["ar"], when["manad"], when["dag"], today()) >= purchase.sale_date


def status_view(round_, genebank_id, with_phone=False):
    """
    StatusView (5.14): a row per active herd of the genebank, and per herd with any report in the round (a withdrawn
    one too), with its state (the first that holds of STATES), the support conditions and the register statistics.
    A fixed number of queries however many herds there are. `with_phone` adds the main member's phone to each row
    (`telefon`, null without one); without it the key is absent.
    """
    import utils.purchase_notice as purchase_notice  # pylint: disable=import-outside-toplevel  # it imports this module

    year, last = round_.report_year, date(round_.report_year, 12, 31)
    in_round = list(
        YearlyHerdReport.select(YearlyHerdReport.id, YearlyHerdReport.herd, YearlyHerdReport.status)
        .join(Herd)
        .where(YearlyHerdReport.round == round_.id, Herd.genebank == genebank_id)
    )
    reports = {
        report.herd_id: report
        for report in YearlyHerdReport.select().where(
            YearlyHerdReport.id.in_([r.id for r in in_round if r.status == "submitted"])
        )
    }
    herds = list(
        Herd.select()
        .where(
            Herd.genebank == genebank_id,
            Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS),
            (Herd.is_active == True) | Herd.id.in_({r.herd_id for r in in_round}),  # noqa: E712
        )
        .order_by(Herd.herd)
    )
    items, drafts, emails = _row_states(herds, round_)
    invitations = _invitations(herds, round_)
    held, stats, pending = innehav(genebank_id, year), statistik(genebank_id, year), _pending_sales(last)
    data = {herd_id: json.loads(report.data) for herd_id, report in reports.items()}
    unstated = sorted({int(i) for body in data.values() for i in body.get("not_stated") or ()})
    waiting, again, bought = _sale_flags(round_, reports)
    notices = purchase_notice.unsettled([herd.id for herd in herds], year)
    extra = {
        row.id: Kanin(
            row.id, SEXES.get(row.sex), row.sex == "eunuch" or bool(row.castration_date and row.castration_date <= last)
        )
        for row in Individual.select(Individual.id, Individual.sex, Individual.castration_date).where(
            Individual.id.in_(sorted({*unstated, *(i for ids in again.values() for i in ids)}))
        )
    }
    phones = {}
    if with_phone:
        for row in (  # the first main member, as in _row_states
            Member.select(Herd.id.alias("herd_id"), Member.phone)
            .join(Herd, on=(Herd.membership == Member.membership))
            .where(Herd.id.in_([h.id for h in herds]), Member.role == "huvudmedlem", Member.end_date.is_null(True))
            .order_by(Member.id)
            .dicts()
        ):
            phones.setdefault(row["herd_id"], row["phone"] or None)
    rows = []
    for herd in herds:
        report, body, item = reports.get(herd.id), data.get(herd.id, {}), items.get(herd.id)
        if report and body.get("ending_genbank"):
            state = "avslutar"
        elif report:
            state = "inskickad"
        elif item and item.state == "vantar_uppfodare":
            state = "blankett_vantar"
        elif item:
            state = "blankett_inkommen"
        elif herd.id in drafts:
            state = "paborjad"
        elif not emails.get(herd.id):
            state = "ingen_epost"
        else:
            state = "ej_rapporterad"
        counted = [kanin for kanin in held.get(herd.id, []) if kanin.individual_id not in pending]
        stat = stats.get(herd.id)
        villkor = support_conditions(counted, stat, report, round_.deadline)
        not_stated, choosing = body.get("not_stated") or [], again.get(herd.id, [])
        # U12 (ej angivna) and FB3 (a rejected sale to choose again): set when the four conditions hold only if
        # those rabbits are counted
        listed = {kanin.individual_id for kanin in counted} | pending
        more, chosen = ([extra[i] for i in ids if i in extra and i not in listed] for ids in (not_stated, choosing))
        facts = (counted, villkor, stat, report, round_.deadline)
        rows.append(
            {
                "herd": herd.herd,
                "herd_name": herd.herd_name,
                "state": state,
                "inbjudan": invitations.get(herd.id),
                "ingen_epost": not emails.get(herd.id),
                "source": report.source if report else None,
                "membership_after_end": body.get("membership_after_end"),
                "received_at": _iso(report.received_at) if report else None,
                "on_time_override": report.on_time_override if report else None,
                "inbox_item_id": (report.inbox_item_id if report else None) or (item.id if item else None),
                "flags": {
                    "ej_angivna": len(not_stated),
                    "ej_angivna_paverkar": _only_with(more, *facts),
                    "forsaljning_vantar": waiting[herd.id],
                    "forsaljning_avvisad": len(choosing),
                    "forsaljning_avvisad_paverkar": _only_with(chosen, *facts),
                    "kopt_efter_inskick": bought[herd.id],
                    "kop_anmalt": notices[herd.id],
                },
                "villkor": villkor,
                "statistik": {
                    "kullar": stat.kullar if stat else 0,
                    "ungar": stat.ungar if stat else 0,
                    "levande_6v": stat.levande_6v if stat else 0,
                    "preliminart": stat.preliminart if stat else False,
                    "honor": stat.honor if stat else 0,
                    "hanar": stat.hanar if stat else 0,
                },
                **({"telefon": phones.get(herd.id)} if with_phone else {}),
            }
        )
    counts = Counter(row["state"] for row in rows)
    return {
        "round": round_json(round_),
        "genebank_id": genebank_id,
        "activated": _activations(round_).where(YearlyReportRoundGenebank.genebank == genebank_id).exists(),
        "counts": {state: counts[state] for state in STATES},
        "rows": rows,
    }


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
PAPER_FIELDS = ("konto", "adress", "telefon", "epost", "publicering")  # the form's "Dina uppgifter"
MATRIKEL_PARTS = {"adress": ("address", "postal_code", "city"), "konto": ("clearing", "konto", "bank")}
UTOM = ("phone", "email", "address")  # the consent keys a Ja may leave out; the name never
CONSENT_LABELS = {"phone": "telefonnummer", "email": "e-postadress", "address": "postnummer och ort"}
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
    sald: dict | None  # {till, ar, manad, dag, kopare, kopare_id}: the buyer object, or a kept buyer's id (K1)


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
        raise _bad("val", "Välj Finns kvar, Död eller Såld.")
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
        # a stored submission names its proposal (forslag), a draft where its kept buyer came from (fran_rapport, read
        # from the server's draft): neither is part of the entry, so equal choices stay equal
        sald = _month(raw.get("sald"), "sald", ("till", "kopare", "forslag", *KEPT_KEYS))
        till, kopare, kopare_id = (raw["sald"].get(key) for key in ("till", "kopare", "kopare_id"))
        if not isinstance(till, str) or not till:
            raise _bad("sald", "Ange köparens besättning, eller utanför genbanken.")
        only_outside = "Köparens namn och ort anges bara vid försäljning utanför genbanken."
        if kopare is not None and (till != "utanfor" or not isinstance(kopare, dict)):
            raise _bad("kopare", only_outside)
        if kopare_id is not None and (till != "utanfor" or not _is_int(kopare_id)):
            raise _bad("kopare_id", only_outside)
        sald = {"till": till, **sald, "kopare": kopare, "kopare_id": kopare_id}
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
    return {"inbox_item_id": item_id, "received_on": received, "signed_on": signed, "matrikel": _matrikel(body)}


def _matrikel(body):
    """The form's "Dina uppgifter", its shape only: check refuses a bad value, so that the dry run lists it."""
    value = body.get("matrikel")
    if value is None:
        return None
    texts = [_keys(value, PAPER_FIELDS, "matrikel").get(key) for key in ("telefon", "epost")]
    for name, parts in MATRIKEL_PARTS.items():
        if value.get(name) is not None:
            texts += _keys(value[name], parts, "matrikel").values()
    if any(text is not None and not isinstance(text, str) for text in texts):
        raise _bad("matrikel", "Fältet ska vara text.")
    if (answer := value.get("publicering")) is not None:  # Ja or Nej, and at Ja what may not be listed
        utom = _keys(answer, ("ja", "utom"), "matrikel").get("utom")
        if not isinstance(answer.get("ja"), bool) or not isinstance(utom, list) or not all(k in UTOM for k in utom):
            raise _bad("matrikel", "Svara Ja eller Nej om Koharen, och vid Ja vad som inte får stå med.")
    return value


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


def _lived(entry, last, on):
    """The entry says the rabbit lived on 31/12: kvar, or a death or a sale after it (5.3)."""
    when = entry.dod or entry.sald
    return entry.val == "kvar" or (when is not None and partial_date(when["ar"], when["manad"], when["dag"], on) > last)


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
    if _lived(entry, last, on):  # what kvar gives
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


def _proposals(report):
    """The report's latest sale proposal per rabbit (5.9); {} without a report."""
    if report is None:
        return {}
    query = SaleProposal.select().where(SaleProposal.report == report.id).order_by(SaleProposal.id)
    return {proposal.individual_id: proposal for proposal in query}


def _keeps(proposal, before, entry):
    """The rabbit's pending proposal still stands for `entry`: the same sale as before and no buyer typed (K5)."""
    return (
        proposal is not None
        and proposal.state == "foreslagen"
        and before is not None
        and same_sale(before.sald, entry.sald)
        and entry.sald.get("kopare") is None
    )


def _without_sale(effects):
    return [e for e in effects if e.kind != "transfer"]


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
    # A 31/12 measurement is written while the herd holds the rabbit, so the report's later sale comes off first;
    # one outside the genebank stays with its buyer, and apply_diff writes the measurement directly (Opus 2).
    if any((e in cur) != (e in want) for e in cur + want if e.kind in ("weight", "bodyfat")):
        later = [c for c in cur if c.kind == "transfer" and c.date > last]
        gone += [c for c in later if c.value[0] not in OUTSIDE_GENEBANK_HERDS]
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
    "inte_klar": "Välj Finns kvar, Död eller Såld.",
    "vikt_saknas": "Vuxna kaniner behöver vikt eller Ej vägd.",
    "vikt_ogiltig": "Ange vikten i kilo, till exempel 2,8.",
    "ej_angiven_digitalt": "Ej angiven finns bara när en blankett matas in.",
    "forsaljning_skotare": "Försäljningen registreras av ägaren eller genbanksansvarig.",
    "salj_via_lank": "Försäljningen registrerar du hos genbanksansvarig. Ring eller mejla.",
    "kopare_saknas": "Skriv köparens namn och ort.",
    "senare_handelse": "Kaninen har en senare händelse i Stamboken. Genbanksansvarig kan rätta.",
    "okand_kanin": "Kaninen finns inte i listan för besättningen.",
    "halsa_saknas": "Välj Inga sjukdomsfall eller defekter, eller Ja.",
    "orsak_kravs": "Skriv varför rapporten ändras.",
    "orsak_kopare": "Skriv inte köparens namn i orsaken.",
    "rundan_stangd": "Rundan är stängd.",
    "inte_innehavare": "Kaninen fanns inte i din besättning 31 december.",
    "dodsdatum_ogiltigt": "Dödsdatumet kan inte vara före födelsen eller senare än i dag.",
    "skrivning_nekad": "Stamboken tog inte emot ändringen för kaninen. Genbanksansvarig kan rätta.",  # _denied
    "ingen_huvudmedlem": "Besättningen saknar huvudmedlem i matrikeln, så ändringen kan inte sparas.",
    "adress_ogiltig": "Kontrollera adressen. Gatuadressen får vara högst 200 tecken och postnumret har fem siffror.",
    "telefon_ogiltig": "Telefonnumret får vara högst 50 tecken.",
    "epost_ogiltig": "Kontrollera e-postadressen.",
    "konto_ogiltigt": "Clearingnumret har 4–5 siffror och kontonumret 5–12 siffror.",
}
# _validate_sale's user: the report never sells into another genebank, since TransferIndividual needs a reason there.
_NOT_ADMIN = SimpleNamespace(is_admin=False)


def _no_sale(individual_id, access):
    """FB5: a caretaker or the link changes no sale the owner registered; the genebank manager corrects it."""
    return _refusal(individual_id, "salj_via_lank" if access.role == "code" else "forsaljning_skotare")


def _refusal(individual_id, code, message=None):
    return Refusal(individual_id, code, message or REFUSALS[code])


def _denied(individual_id, detail):
    """
    U8, for every Skicka and Dra tillbaka: a void or a write refused for a later row is senare_handelse; any other
    refusal is skrivning_nekad with its own text, or the table's when it has none (IndividualRefused's are English).
    """
    if detail in (REPORT_LATER_ROW, DATE_BEFORE_LATEST):
        return _refusal(individual_id, "senare_handelse")
    return _refusal(individual_id, "skrivning_nekad", detail)


def _vikt_ovanlig(individual_id, vikt):
    """D17: a valid weight outside 1,0–6,5 kg warns and never blocks; None for any other weight."""
    if vikt is None or not 0 < vikt <= 20 or 1.0 <= vikt <= 6.5:
        return None
    return Refusal(individual_id, "vikt_ovanlig", f"Stämmer {format(vikt, 'g').replace('.', ',')} kg?")


def _death_possible(dod, birth, on):
    """
    Codex 3: the death's resolved date is on or after the birth (`birth`, report_list's ISO date) and not after `on`,
    today in Stockholm. A month after `on` is refused without its day too, though partial_date takes it back to `on`.
    """
    died = partial_date(dod["ar"], dod["manad"], dod["dag"], on)
    return (
        (dod["ar"], dod["manad"]) <= (on.year, on.month)
        and died <= on
        and not (birth and died < date.fromisoformat(birth))
    )


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


def _register_refusals(individual_id, entry, remove, add, ops, admin=False, kept_buyer=None):
    """
    What the writes would meet in the register: each void under report_void_denial, latest first as apply_diff
    runs them, then a row behind a later one (DATE_BEFORE_LATEST), then each new sale under _validate_sale and the
    buyer rules: a sale outside the genebank needs a typed buyer or a kept one (`kept_buyer`, _kept_contact). A row
    behind a later one is senare_handelse; any other denial keeps its text (U8). The reason's check against the
    buyers is _reason_refusals', once for the report.
    """
    if not any(e.kind in ROW_KINDS for e in remove + add):
        return []
    rows = list(
        HerdTracking.select(HerdTracking, Herd)
        .join(Herd, on=(HerdTracking.herd == Herd.id))
        .where(HerdTracking.individual == individual_id, ht_not_voided())
    )
    kept, gone = sorted(rows, key=ht_sort_key), {e.ref for e in remove if e.kind in ROW_KINDS}
    voided = sorted((row for row in rows if row.id in gone), key=ht_sort_key, reverse=True)
    rabbit, user = Individual.get_by_id(individual_id) if voided else None, SimpleNamespace(is_admin=admin)
    for row in voided:
        if denial := report_void_denial(user, row, kept, rabbit, ops):
            return [_denied(individual_id, denial)]
        kept.remove(row)
    if kept and any(e.date < coerce_date(kept[-1].herd_tracking_date) for e in add if e.kind in ROW_KINDS):
        return [_refusal(individual_id, "senare_handelse")]
    from blueprints.individuals import _validate_sale  # pylint: disable=import-outside-toplevel  # it imports utils

    refusals = []
    for sale in (e for e in add if e.kind == "transfer"):
        kopare, form = entry.sald["kopare"], {"selling_date": sale.date.isoformat(), "herd": sale.value[0]}
        if error := _validate_sale(_sale_view(individual_id, kept), form, _NOT_ADMIN, kopare):
            refusals.append(_refusal(individual_id, "forsaljning", error.replace("Försäljningsdatumet", "Säljdatumet")))
        if sale.value[0] in OUTSIDE_GENEBANK_HERDS and kopare is None and kept_buyer is None:
            refusals.append(_refusal(individual_id, "kopare_saknas"))
        elif sale.value[0] in OUTSIDE_GENEBANK_HERDS and kopare is not None:
            try:
                buyer_contact_fields(kopare)
            except HerdTrackingInvalid as exc:
                refusals.append(_refusal(individual_id, "kopare", str(exc)))
    return refusals


def _kept_contact(herd, round_, entry, claim):
    """
    K1: the buyer kept across Dra tillbaka that a sale outside the genebank links again in place of a typed buyer,
    or None. The body names it (kopare_id) and the server's draft says where it came from (`claim`). It is taken
    only when that report is a voided one of the same herd and round, one of its operations wrote a TRANSFER of this
    rabbit holding the buyer, and no active row holds it now.
    """
    kopare_id = entry.sald["kopare_id"] if entry.sald and entry.sald["kopare"] is None else None
    if kopare_id is None or claim is None or claim["kopare_id"] != kopare_id or not _is_int(claim["fran_rapport"]):
        return None
    report = YearlyHerdReport.get_or_none(
        (YearlyHerdReport.id == claim["fran_rapport"])
        & (YearlyHerdReport.herd == herd.id)
        & (YearlyHerdReport.round == round_.id)
        & (YearlyHerdReport.status == "voided")
    )
    if report is None:
        return None
    sold = HerdTracking.select().where(
        HerdTracking.individual == entry.individual_id,
        HerdTracking.kind == "TRANSFER",
        HerdTracking.holder_contact == kopare_id,
        HerdTracking.operation_id.in_(sorted(report_ops(report))),
    )
    held = HerdTracking.select().where(HerdTracking.holder_contact == kopare_id, ht_not_voided())
    return kopare_id if sold.exists() and not held.exists() else None


def _reason_refusals(reason, rabbit_ids, names=()):
    """
    Opus 1, 4: a typed reason that names a buyer of the rabbits' rows, or one of `names`, the buyers the submission
    types and the report's pending proposals hold, is refused once for the report. void_herd_tracking checks the same
    rows per rabbit, so a dry run that passes here never meets that 422; the reason is stored in the submission and on
    the voided rows.
    """
    try:
        _reject_buyer_name([reason], rabbit_ids, names=names)
    except HerdTrackingInvalid:
        return [_refusal(None, "orsak_kopare")]
    return []


def _typed_buyers(sub):
    """The buyer names the submission types; kopare is checked later, so here only a name that is text counts."""
    buyers = (entry.sald["kopare"] for entry in sub.rabbits.values() if entry.sald)
    return [buyer["name"] for buyer in buyers if isinstance(buyer, dict) and isinstance(buyer.get("name"), str)]


def _waiting_buyers(proposals):
    """The buyer names the pending proposals hold, which no BuyerContact has yet: a reason names none of them."""
    pending = (p.buyer for p in proposals if p.state == "foreslagen" and p.buyer)
    return [buyer["name"] for buyer in pending if isinstance(buyer.get("name"), str)]


def check(herd, round_, access, report, sub, *, on: date) -> tuple[list[Refusal], list[Refusal]]:
    """
    The dry run (5.4 point 1): (refusals, warnings) for the submission `sub` on the herd's current `report`, as of
    `on`. It takes no lock and writes nothing; Skicka runs it again under the locks.
    """
    if not access.reads_buyers:
        sub = without_reason(sub)
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
    ops = {str(op) for submission in submissions for op in submission.operation_ids}
    refusals, warnings = [], []
    if not sub.reason and (
        (access.source == "paper" and report is not None) or (late and (access.editor or access.role == "helper"))
    ):
        refusals.append(_refusal(None, "orsak_kravs"))
    # A null in the latest submission came from paper, or an editor kept it there (case 8 by phone).
    kept_null = access.editor and latest is not None and latest.get("health") is None
    ending = sub.report["ending_genbank"]  # 5.7, fråga 18: an ending needs neither choices nor a health answer
    if access.source != "paper" and sub.report["health"] is None and not kept_null and not ending:
        refusals.append(_refusal(None, "halsa_saknas"))
    rows = {row["id"]: row for row in report_list(herd, year, report)}
    strangers = [rabbit for rabbit in sub.rabbits if rabbit not in rows]
    strangers += [d["individual_id"] for d in sub.report["defects"] if d["individual_id"] not in rows]
    refusals += [_refusal(rabbit, "okand_kanin") for rabbit in strangers]
    # Only the report's own rabbits: another herd's rabbit would make the refusal an oracle on its buyer's name.
    own = [rabbit for rabbit in sub.rabbits if rabbit in rows]
    proposals = _proposals(report)
    refusals += _reason_refusals(sub.reason, own, _typed_buyers(sub) + _waiting_buyers(proposals.values()))
    draft = _draft(herd, round_)  # K1: a proposal takes no kept buyer, so only a role that sells reads them (F1)
    claims = _kept_claims(draft.data) if draft is not None and access.can_sell else {}
    for rabbit, row in rows.items():
        entry, before = sub.rabbits.get(rabbit), before_entries.get(rabbit)
        if entry is None:
            if (
                row["state"] == "att_valja" and not sub.report["ending_genbank"]
            ):  # 5.7: an ending genebank needs no choices
                refusals.append(_refusal(rabbit, "inte_klar"))
            continue
        kept = access.editor and before is not None and before.val == "ej_angiven"
        if entry.val == "ej_angiven" and access.source != "paper" and not kept:
            refusals.append(_refusal(rabbit, "ej_angiven_digitalt"))
            continue
        # P39a: it writes nothing and is not refused; a rejection rewrote its entry and moved the revision (S1)
        if entry == before:
            continue
        if row["state"] != "att_valja":
            refusals.append(_refusal(rabbit, "senare_handelse"))
            continue
        if entry.val == "ej_angiven":  # it writes nothing, but what it takes off still meets the register (M1)
            remove, add = diff(current(report, rabbit), [], last, before, entry)
            refusals += _register_refusals(rabbit, entry, remove, add, ops, access.role == "admin")
            continue
        if entry.dod and not _death_possible(entry.dod, row["birth_date"], on):
            refusals.append(_refusal(rabbit, "dodsdatum_ogiltigt"))
            continue
        if _lived(entry, last, on) and _holder_on(rabbit, last, ops) != herd.id:  # 5.4 point 1, before the attest
            refusals.append(_refusal(rabbit, "inte_innehavare"))
            continue
        if entry.vikt is not None and not 0 < entry.vikt <= 20:
            refusals.append(_refusal(rabbit, "vikt_ogiltig"))
        elif warning := _vikt_ovanlig(rabbit, entry.vikt):
            warnings.append(warning)
        if (
            entry.val == "kvar"
            and row["adult"]
            and entry.vikt is None
            and not entry.ej_vagd
            and not sub.report["ending_genbank"]
        ):
            refusals.append(_refusal(rabbit, "vikt_saknas"))
        want = wanted(entry, row, report, herd, year, on)
        if _keeps(proposals.get(rabbit), before, entry):  # the pending proposal holds the sale
            want = _without_sale(want)
        remove, add = diff(current(report, rabbit), want, last, before, entry)
        # FB5: a sale the owner registered is the register's; a new sale by this role is a proposal, checked as a sale
        if not access.can_sell and any(e.kind == "transfer" for e in remove):
            refusals.append(_no_sale(rabbit, access))
            continue
        sale = next((e for e in add if e.kind == "transfer"), None)
        # A proposal sells from this herd, which writes no row to check it: the herd holds the rabbit on the sale
        # date, by all its rows as approve reads them (Skicka runs this under the rabbit's lock)
        if not access.can_sell and sale is not None and _holder_on(rabbit, sale.date, set()) != herd.id:
            refusals.append(_refusal(rabbit, "senare_handelse"))
            continue
        kept = _kept_contact(herd, round_, entry, claims.get(str(rabbit)))
        refusals += _register_refusals(rabbit, entry, remove, add, ops, access.role == "admin", kept)
    if access.source == "paper":
        refusals += _matrikel_refusals(herd, sub.paper["matrikel"])
    return refusals, warnings


# Contact changes from paper (5.5, fråga 25 and 34, D7, D8, D19): written without reading

A23 = "kontakt.andrad_fran_blankett"
FIELD_LABELS = dict(zip(PAPER_FIELDS, ("konto", "adress", "telefon", "e-post", "publicering"), strict=True))
# U10: the columns the matrikel's logs name, as the form's fields
COLUMN_FIELDS = {
    "address": "adress",
    "postal_code": "adress",
    "city": "adress",
    "phone": "telefon",
    "email": "epost",
    "bank_account_number": "konto",
    "bank_name": "konto",
}


def _contact(matrikel) -> tuple[dict, list[Refusal]]:
    """
    The form's contact changes as {field: {column: value}}, each value as the matrikel stores it, and the dry run's
    refusals of the rest (5.5). A blank part is no change: paper never clears the matrikel.
    """
    from blueprints.common import EMAIL_RE  # pylint: disable=import-outside-toplevel  # as _validate_sale

    given, contact, refusals = matrikel or {}, {}, []
    adress = {part: text.strip() for part, text in (given.get("adress") or {}).items() if text and text.strip()}
    if adress:
        try:
            postal = parse_postal_fields({part: text for part, text in adress.items() if part != "address"})
        except AddressValidationError:
            postal = None
        if postal is None or len(adress.get("address", "")) > 200:
            refusals.append(_refusal(None, "adress_ogiltig"))
        else:  # as patch_me_contact writes it (Codex 13)
            parts = [part for part in MATRIKEL_PARTS["adress"] if part in adress]
            contact["adress"] = {part: postal.get(part, adress[part]) for part in parts}
    telefon = (given.get("telefon") or "").strip()
    if len(telefon) > 50:  # R029
        refusals.append(_refusal(None, "telefon_ogiltig"))
    elif telefon:
        contact["telefon"] = {"phone": telefon}
    epost = (given.get("epost") or "").strip().lower()
    if epost and (len(epost) > 255 or not EMAIL_RE.match(epost)):
        refusals.append(_refusal(None, "epost_ogiltig"))
    elif epost:
        contact["epost"] = {"email": epost}
    konto = given.get("konto") or {}
    clearing, number = (re.sub(r"[\s.-]", "", konto.get(part) or "") for part in ("clearing", "konto"))
    bank = (konto.get("bank") or "").strip() or None
    if clearing or number:  # D8: digits only, the clearing 4–5 and the account 5–12
        if not (re.fullmatch("[0-9]{4,5}", clearing) and re.fullmatch("[0-9]{5,12}", number)) or len(bank or "") > 100:
            refusals.append(_refusal(None, "konto_ogiltigt"))
        else:
            # shortcut: the account lives on the herd, migration 44 moves it to the membership; write it there then
            contact["konto"] = {"bank_account_number": f"{clearing}-{number}", "bank_name": bank}
    return contact, refusals


def _main_member(herd):
    """The herd's active main member per the matrikel (inbox.herd_holder), never an erased one."""
    member = inbox.herd_holder(herd.id)
    return member if member is not None and not is_anonymized(member) else None


def _matrikel_refusals(herd, matrikel):
    """check's refusals of the form's contact changes; any of them, or a Koharen answer, needs the main member."""
    contact, refusals = _contact(matrikel)
    if (contact or refusals or (matrikel or {}).get("publicering") is not None) and _main_member(herd) is None:
        refusals.insert(0, _refusal(None, "ingen_huvudmedlem"))
    return refusals


def later_fields(herd, membership, member, signed_on: date, own=frozenset()) -> set[str]:
    """
    D19: the PAPER_FIELDS the matrikel changed after the form's date, that is from the next day in Stockholm: the
    account by the herd's audit_log, the consent by publication_consent_change, and the rest by matrikel_audit, whose
    created_at is naive server time. Phone and e-mail count only from rows about `member`, and every swap of the main
    member counts for them (I2). The paper writes of the submissions in `own`, the herd's report for the round, do not
    count, so that Ändra from paper can correct its own typo (I1): their kontakt_andrad rows, the herd's audit rows
    of the same transactions, and their paper consent rows. That holds only for a form not withdrawn and signed on or
    before `signed_on`: a newer signed form's write still wins over an older form entered after it.
    """
    # shortcut: the matrikel importer in cli/members.py leaves no trace, so this misses its changes; log them if it
    # ever runs during a round.
    after = datetime.combine(signed_on + timedelta(days=1), datetime.min.time(), STOCKHOLM)
    own = {
        submission.id
        for submission in YearlyReportSubmission.select(YearlyReportSubmission.id, YearlyReportSubmission.data)
        .join(YearlyHerdReport)
        .where(
            YearlyReportSubmission.id.in_(own),
            YearlyReportSubmission.source == "paper",
            YearlyHerdReport.status != "voided",
        )
        if date.fromisoformat(submission.data["signed_on"]) <= signed_on
    }
    audits = MatrikelAudit.select(MatrikelAudit.action, MatrikelAudit.payload).where(
        MatrikelAudit.membership == membership.id,
        MatrikelAudit.action.in_(("membership_updated", "person_updated", "kontakt_andrad", "main_member_changed")),
        MatrikelAudit.created_at >= after.astimezone().replace(tzinfo=None),
    )
    fields, transactions = set(), set()
    for audit in audits:
        payload = audit.payload or {}
        if payload.get("submission_id") in own:
            transactions.add(payload.get("transaction_id"))
            continue
        if audit.action == "main_member_changed":  # the form's signer may not be the main member written to
            fields |= {"telefon", "epost"}
        mine = payload.get("person_id", member.id) == member.id  # membership_updated names no person
        for column in payload.get("fields") or payload.get("after") or ():
            if column in COLUMN_FIELDS and (mine or COLUMN_FIELDS[column] == "adress"):
                fields.add(COLUMN_FIELDS[column])
    account = AuditLog.select(AuditLog.transaction_id).where(
        AuditLog.table_name == "herd",
        AuditLog.record_id == str(herd.id),
        AuditLog.operation == "UPDATE",  # an INSERT lists every column it filled
        AuditLog.changed_at >= after,
        AuditLog.changed_fields.contains_any("bank_account_number", "bank_name"),
    )
    if any(row.transaction_id not in transactions for row in account):
        fields.add("konto")
    consent = PublicationConsentChange.select(PublicationConsentChange.submission_id).where(
        PublicationConsentChange.membership == membership.id, PublicationConsentChange.at >= after
    )
    if any(row.submission_id not in own for row in consent):  # a profile row has none
        fields.add("publicering")
    return fields


def _same(column, stored, value):
    """The matrikel already holds `value`: the account by its digits (D8), the e-mail in any case."""
    if column == "bank_account_number":
        return re.sub(r"\D", "", stored or "") == re.sub(r"\D", "", value)
    stored = (stored or "").strip()
    return (stored.lower() if column == "email" else stored) == value


def apply_paper_matrikel(herd, membership, member, submission, item, user, matrikel, signed_on):
    """
    5.5: the form's consent and contact changes written into the matrikel and never read back: the consent first and
    the address to `membership`, phone and e-mail to its main `member`, the account to the herd (D8). The caller holds
    the membership's lock and read both under it. Only a value that differs counts, the bank going with a new account,
    and a field the matrikel changed after `signed_on` is skipped (D19), unless the herd's report for the round wrote
    it from paper itself (I1). For the consent only what it adds is skipped: a No or fewer details go at once (fråga
    27). Each write is save(only=…): a whole row would write back a stale user_id. The consent's log is its
    publication_consent_change row; every contact write gets one kontakt_andrad row with the column names and
    `submission_id`, and with the transaction for the account, which ties the herd's audit row to it. Returns
    (written, skipped) as PAPER_FIELDS.
    """
    stored = Herd.get_by_id(herd.id)  # the account as it is now, not as the route read it
    report = YearlyHerdReport.get_by_id(submission.report_id)
    same = (YearlyHerdReport.herd == report.herd_id) & (YearlyHerdReport.round == report.round_id)
    own = YearlyReportSubmission.select(YearlyReportSubmission.id).join(YearlyHerdReport).where(same)
    rows = {"adress": membership, "telefon": member, "epost": member, "konto": stored}
    changes = {}
    for name, columns in _contact(matrikel)[0].items():
        row = rows[name]
        if name == "konto":
            moved = not _same("bank_account_number", row.bank_account_number, columns["bank_account_number"])
            differ = columns if moved else {}
        else:
            differ = {
                column: value for column, value in columns.items() if not _same(column, getattr(row, column), value)
            }
        if differ:
            changes[name] = differ
    answer = (matrikel or {}).get("publicering")
    consent = consent_from_answer(answer["ja"], answer["utom"]) if answer is not None else None
    consent = None if consent == stored_consent(membership) else consent
    asked = changes or consent is not None
    later = later_fields(stored, membership, member, signed_on, {row.id for row in own}) if asked else set()
    skipped = [name for name in PAPER_FIELDS if name in changes and name in later]
    written = {name: changes[name] for name in PAPER_FIELDS if name in changes and name not in later}
    if consent is not None and "publicering" in later:  # only what the form adds waits for the member
        current = effective_consent(membership)
        narrowed = {key: allowed and current[key] for key, allowed in consent.items()}
        skipped += ["publicering"] if narrowed != consent else []
        consent = narrowed if narrowed != current else None  # a stored blob of fewer keys is no reason to write
    consented = consent is not None and set_consent(
        membership,
        consent,
        source="paper",
        text_version=CONSENT_TEXT_VERSION,
        user=user.id,
        report=submission.report_id,
        submission=submission.id,
        at=submission.created_at,
    )
    old_email = member.email
    for model, row, names, stamp in (
        (Membership, membership, ("adress",), [Membership.updated_at]),
        (Member, member, ("telefon", "epost"), [Member.updated_at]),
        (Herd, stored, ("konto",), []),
    ):
        columns = {column: value for name in names for column, value in written.get(name, {}).items()}
        for column, value in columns.items():
            setattr(row, column, value)
        if columns:
            row.save(only=[getattr(model, column) for column in columns] + stamp)
    if written:
        payload = {
            "person_id": member.id,
            "fields": [column for columns in written.values() for column in columns],
            "source": "paper",
            "inbox_item_id": item.id,
            "submission_id": submission.id,
        }
        if "konto" in written:  # the herd's audit row has the same transaction_id (txid_current() by default)
            payload["transaction_id"] = DB_PROXY.execute_sql("SELECT txid_current()").fetchone()[0]
        if "epost" in written:  # as person_updated has it: the login's 7-day rule reads "email" in "after"
            payload |= {"before": {"email": old_email}, "after": {"email": member.email}}
        write_matrikel_audit(user, "kontakt_andrad", membership, payload)
    return list(written) + (["publicering"] if consented else []), skipped


def log_and_mail_paper_contact(herd, item, submission, user, member, fields, skipped, old_email):
    """
    The paper path's log and Å23 (5.5, 5.10). The item's event names the fields, never a value (D7), and receipt()
    reads it back. Å23 goes to the matrikel's e-mail as it was before the change: when the e-mail changed, through an
    already confirmed member_change_request, since "member" reads the new one when the mail goes. Without an old
    e-mail no mail goes and the log is all (an SMS may come with an SMS service, spec 16).
    """
    if not (fields or skipped):
        return
    inbox.log_event(item, user, "matrikel_andrad", falt=fields, hoppade=skipped, submission_id=submission.id)
    if not (fields and old_email):
        return
    recipient = ("member", member.id)
    if "epost" in fields:
        at = submission.created_at
        request = MemberChangeRequest.create(
            member=member.id,
            submission=submission.id,
            kind="epost",
            value={"old": old_email, "new": member.email},
            access_code=None,
            created_at=at,
            old_confirmed_at=at,
            confirmed_at=at,
        )
        recipient = ("email_change_old", request.id)
    enqueue_mail(
        A23,
        *recipient,
        {"submission_id": submission.id} | {field: int(field in fields) for field in PAPER_FIELDS},
        ref=("yearly_report_submission", submission.id),
        herd=herd,
        genebank=herd.genebank_id,
        dedupe_key=f"{A23}:{submission.id}",
        created_by=user.id,
    )


def _later_change(name):
    message = f"Matrikeln har ändrats efter blankettens datum ({FIELD_LABELS[name]}). Fråga medlemmen."
    return Refusal(None, "senare_andring", message)


def _contact_event(submission):
    """The paper submission's matrikel_andrad event, so that every retry's receipt names the same fields."""
    item_id = submission.data.get("inbox_item_id")
    if item_id is None:
        return {}
    events = InboxEvent.select(InboxEvent.detail).where(
        InboxEvent.item == item_id, InboxEvent.kind == "matrikel_andrad"
    )
    return next((event.detail for event in events if event.detail["submission_id"] == submission.id), {})


def _lock_matrikel(herd):
    """
    The herd's membership FOR UPDATE, which the matrikel's own writers take first, then the herd's row, whose account
    apply_paper_matrikel checks and writes (Opus 5): an account change on the herd page waits, or comes before
    later_fields reads it. FOR NO KEY UPDATE, as lock_individuals, so rows that refer to the herd are not held up.
    The main member is read under them: (membership, member), each None when missing. A herd moved to another
    membership meanwhile is a 409.
    """
    membership_id = Herd.select(Herd.membership).where(Herd.id == herd.id).scalar()
    if membership_id is None:
        return None, None
    membership = Membership.select().where(Membership.id == membership_id).for_update().get()
    locked = Herd.select(Herd.membership).where(Herd.id == herd.id).for_update("FOR NO KEY UPDATE")
    if locked.scalar() != membership_id:
        raise ArsrapportError(409, "Besättningen bytte medlemskap samtidigt. Försök igen.")
    return membership, _main_member(herd)


# Skicka (5.4 points 2–5): the submission in one transaction, its key and its fixed receipt

KEY_TAKEN = "Rapporten är redan skickad med den här nyckeln. Ladda om sidan."
MEASUREMENTS = ("weight", "bodyfat")


class ReportGrant:
    """
    individual_commands.Grant for a report's writes, which collects the operation ids every execute logged. Logged
    in it gives no role, since roles_for does, so the can_edit guard applies. On paper the item's InboxGrant gives a
    helper HANDLAGGARE and leaves everyone's trace. `report_ops` (the report's own operations) gives RAPPORT, for
    the backouts of Ändra; Undo checks them. Both only for a rabbit in the report's herd now (`herd`, or the code's).
    With `code` (the link, step 3) RAPPORT is the code's only role, and without `report_ops` only for a rabbit on
    the report's list (`report`: its latest submission's rabbits too).
    """

    def __init__(self, inbox_grant=None, report_ops=frozenset(), code=None, report=None, herd=None):
        self.inbox_grant, self.report_ops = inbox_grant, frozenset(report_ops)
        self.code, self.report, self.herd, self._listed = code, report, herd, None
        self.operation_ids = []

    def roles(self, user, individual):
        held = self.inbox_grant.roles(user, individual) if self.inbox_grant is not None else frozenset()
        # FA1, for a login as well: RAPPORT only for a rabbit that is in the report's herd now. A rabbit a manager
        # moved on, or a sale approved, is no longer the report's to write or undo.
        herd_id = self.code.herd_id if self.code is not None else self.herd.id if self.herd is not None else None
        if herd_id is not None and individual.current_herd.id != herd_id:
            return held
        if self.report_ops:  # Undo checks the operation itself
            return held | {Role.RAPPORT}
        if self.code is None:
            return held
        if self._listed is None:  # once, before the first write of the request
            herd, year = Herd.get_by_id(self.code.herd_id), self.code.round.report_year
            self._listed = {row["id"] for row in report_list(herd, year, self.report)}
        return held | ({Role.RAPPORT} if individual.id in self._listed else frozenset())

    def roles_in(self, user, herd):
        """For the litter commands (4b), which write in the litter's herd and not on a listed rabbit (L2)."""
        held = self.inbox_grant.roles_in(user, herd) if self.inbox_grant is not None else frozenset()
        return held | {Role.RAPPORT} if self.code is not None and self.code.herd_id == herd.id else held

    def record(self, ctx):
        self.operation_ids += [str(row["operation_id"]) for row in ctx.log_rows]
        if self.inbox_grant is not None:
            self.inbox_grant.record(ctx)


def request_hash(sub: Submission) -> str:
    """
    D21: HMAC-SHA256 with the app's SECRET_KEY over the parsed submission without its key and revision, with the
    matrikel and every buyer. Nothing in it depends on today, so a retry from an old tab matches.
    """
    fields = {name: value for name, value in asdict(sub).items() if name not in ("key", "revision")}
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hmac.new(current_app.secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def find_submission(key, herd, round_, user, request_hash):
    """
    The submission whose receipt a retry gets: the key's, when the same user, or the same link (never one for the
    other), sent it for the herd and round, its report is still submitted and the request hash is equal (D21;
    `request_hash` may be a function of whether the submission was a link's). Any
    other use of the key is a 409; an unknown key is None. The route asks before report_access, so a retry after
    the item closed gets its receipt.
    """
    if key is None:
        return None
    actors = user if isinstance(user, (list, tuple)) else [user]  # a login and the links of the session
    saved = (
        YearlyReportSubmission.select(YearlyReportSubmission, YearlyHerdReport)
        .join(YearlyHerdReport)
        .where(YearlyReportSubmission.submission_key == key)
        .first()
    )
    if saved is None:
        return None
    report = saved.report
    saved_by = ("code", saved.access_code_id) if saved.access_code_id is not None else ("user", saved.user_id)
    mine = any(saved_by == actor_key(actor) for actor in actors)
    # The hash is made as the submission's own actor was treated: a link's reason was dropped (without_reason).
    digest = request_hash(saved.access_code_id is not None) if callable(request_hash) else request_hash
    if (
        mine
        and (report.herd_id, report.round_id, report.status) == (herd.id, round_.id, "submitted")
        and hmac.compare_digest(saved.request_hash, digest)
    ):
        return saved
    raise ArsrapportError(409, KEY_TAKEN)


def _waiting_sales(data):
    """The rabbits (ids as text) whose sale in a submission's data was a pending proposal when it was sent."""
    rabbits = data.get("rabbits") or {}
    return {key for key, entry in rabbits.items() if ((entry or {}).get("sald") or {}).get("forslag") is not None}


def receipt(submission) -> dict:
    """
    Receipt, from the submission row and its events alone, so every retry gets the same one, also after a later change
    (D21): the summary and the weight warnings come from its data, the matrikel's fields and warnings from its
    matrikel_andrad event. `vantar` counts the sales among `salda` that were pending proposals then (the data names
    them).
    """
    entries, event = _entries(submission.data.get("rabbits") or {}), _contact_event(submission)
    chosen = Counter(entry.val for entry in entries.values())
    waiting = len(_waiting_sales(submission.data))
    warnings = [_vikt_ovanlig(rabbit, entry.vikt) for rabbit, entry in sorted(entries.items())]
    warnings += [_later_change(field) for field in event.get("hoppade", [])]
    return {
        "submission_id": submission.id,
        "report_id": submission.report_id,
        "created_at": submission.created_at.astimezone(timezone.utc).isoformat(),
        "source": submission.source,
        "summary": {
            "kvar": chosen["kvar"],
            "doda": chosen["dod"],
            "salda": chosen["sald"],
            "vantar": waiting,
            "ej_angivna": chosen["ej_angiven"],
        },
        "matrikel": event.get("falt", []),
        "warnings": [asdict(warning) for warning in warnings if warning],
    }


def submitted_body(sub: Submission) -> dict:
    """
    The submission's data (D10): the body rebuilt from the parsed submission, so only what was validated is kept.
    Each rabbit keeps its chosen branch alone, and there is no matrikel, buyer (typed or kept), key or revision.
    _entries reads it back as parsed.
    """
    rabbits = {}
    for rabbit, entry in sub.rabbits.items():
        stored = {key: value for key, value in asdict(entry).items() if key != "individual_id"}
        if entry.sald is not None:
            stored["sald"] = {key: value for key, value in entry.sald.items() if key not in ("kopare", "kopare_id")}
        rabbits[str(rabbit)] = stored
    body = {"reason": sub.reason, "rabbits": rabbits} | {key: sub.report[key] for key in BODY_KEYS if key in sub.report}
    if sub.paper is not None:
        paper = sub.paper
        body |= {"inbox_item_id": paper["inbox_item_id"]} | {k: _iso(paper[k]) for k in ("received_on", "signed_on")}
    return body


def _lock_items(ids, form_id=None, report=None, kept=(), notices=()):
    """
    The queue's items that may show the buyers of the rabbits' sales (buyer_items), the paper form's own item, the
    kontroll items of `report`'s pending sale proposals (K4) and the purchase `notices` an approval settles (Task 5),
    locked in one ascending pass before any litter or rabbit: the order of the queue (item, litters, rabbits) and of
    its bulk assignment, so the voids of Ändra and Dra tillbaka, and a proposal taken back or decided, lock only
    items already held and no cycle forms (Codex 4, Opus 3, Codex re-review 2). The voided sales holding the `kept`
    buyers count too (K1): Skicka links them again or deletes them. Returns their ids: _lock_form checks the form's
    item again under it, and _lock_rabbits the buyers' set.
    """
    rows = HerdTracking.select().where(
        (HerdTracking.individual.in_(ids) & ht_not_voided()) | HerdTracking.holder_contact.in_(sorted(kept))
    )
    proposed = set()
    if report is not None:  # the report's lock keeps this set as read
        query = SaleProposal.select(SaleProposal.inbox_item_id).where(
            SaleProposal.report == report.id,
            SaleProposal.state == "foreslagen",
            SaleProposal.inbox_item_id.is_null(False),
        )
        proposed = {proposal.inbox_item_id for proposal in query}
    wanted = sorted(buyer_items(rows) | proposed | set(notices) | ({form_id} if form_id is not None else set()))
    if not wanted:
        return set()
    query = InboxItem.select(InboxItem.id).where(InboxItem.id.in_(wanted)).order_by(InboxItem.id).for_update()
    return {item_id for (item_id,) in query.tuples()}


def _lock_rabbits(ids, items):
    """
    The rabbits' litters, then the rabbits, each in ascending order, once _lock_items holds `items`. A rabbit moved
    to another litter, or a buyer's item that has appeared since, is a 409.
    """

    def litters():
        return dict(Individual.select(Individual.id, Individual.breeding).where(Individual.id.in_(ids)).tuples())

    before = litters()
    lock_breedings(litter for litter in before.values() if litter is not None)
    lock_individuals(ids)
    if litters() != before:
        raise ArsrapportError(409, "Kaninen ändrades samtidigt. Försök igen.")
    if not buyer_items(HerdTracking.select().where(HerdTracking.individual.in_(ids), ht_not_voided())) <= items:
        raise ArsrapportError(409, QUEUE_CHANGED)


def _measured(effect, rabbit):
    """The ids of the rabbit's stored measurements with the effect's date and value (weights to two decimals)."""
    if effect.kind == "weight":
        rows = Weight.select().where(Weight.individual == rabbit, Weight.weight_date == effect.date)
        return [row.id for row in rows if round(row.weight, 2) == effect.value[0]]
    rows = Bodyfat.select().where(
        Bodyfat.individual == rabbit, Bodyfat.bodyfat_date == effect.date, Bodyfat.bodyfat == effect.value[0]
    )
    return [row.id for row in rows]


def _command(effect, rabbit, herd, report, entry):
    """The command that writes `effect`; SetMeasurements gets the stored list as stored, so nothing is replaced."""
    day = effect.date.isoformat()
    if effect.kind == "attest":
        return RecordAttestation(herd.herd, day, report=report.id)
    if effect.kind == "death":
        return RecordDeath({"death_date": day, "butchered": effect.value[1], "death_note": effect.value[2]})
    if effect.kind == "transfer":  # check() let a kopare_id through only as this sale's kept buyer (K1)
        kopare = entry.sald["kopare"]
        return TransferIndividual(
            effect.value[0], day, buyer=kopare, buyer_contact_id=entry.sald["kopare_id"] if kopare is None else None
        )
    if effect.kind == "weight":
        stored = [{"weight": w.weight, "date": w.weight_date.isoformat()} for w in Weight.filter(individual=rabbit)]
        return SetMeasurements(weights=[*stored, {"weight": effect.value[0], "date": day}])
    stored = [{"bodyfat": b.bodyfat, "date": b.bodyfat_date.isoformat()} for b in Bodyfat.filter(individual=rabbit)]
    return SetMeasurements(bodyfat=[*stored, {"bodyfat": effect.value[0], "date": day}])


def _write(user, rabbit, effects, herd, report, entry, grant, last):
    """
    The rabbit's `effects` through execute in `order` (5.4 point 3): once for those up to 31 December, then once
    for those after it. A measurement already stored with its date and value is skipped. The caller holds the
    rabbit's lock, so what is read here stays as read. Returns the added measurements, with the ids read back.
    """
    effects = sorted(effects, key=lambda e: order(e, last))
    effects = [e for e in effects if e.kind not in MEASUREMENTS or not _measured(e, rabbit)]
    added = []
    for batch in ([e for e in effects if e.date <= last], [e for e in effects if e.date > last]):
        if not batch:
            continue
        commands = [_command(e, rabbit, herd, report, entry) for e in batch]
        execute(user, rabbit, lambda ctx, commands=commands: commands, grant=grant)
        added += [
            {
                "individual_id": rabbit,
                "kind": e.kind,
                "id": max(_measured(e, rabbit)),  # the newest: the rabbit is locked until commit
                "date": e.date.isoformat(),
                "value": e.value[0],
            }
            for e in batch
            if e.kind in MEASUREMENTS
        ]
    return added


def apply_diff(
    report,
    herd,
    user,
    grant,
    rabbit_id,
    want: list[Effect],
    prev_entry,
    entry,
    last,
    *,
    reason=None,
    keep_sales=False,
    keep_buyer_until=None,
):
    """
    Ändra for one rabbit (D5): the report's current effects that `want` lacks come off, the latest first (a January
    sale before the attestation), then what is missing is written as Skicka writes it. The voids and the Undo go
    through the report's right (report_ops) with `reason`, else REPORT_UNDO_REASON. A voided sale outside the
    genebank takes its buyer with it (kopare's _drop_orphan_buyers), or keeps it until `keep_buyer_until` (Dra
    tillbaka, K1). With `keep_sales` the report's sales stay (FB5). Refusals raise; the caller holds the locks.
    Returns the added measurements, as _write does.
    """
    cur = current(report, rabbit_id)
    remove, add = diff(cur, want, last, prev_entry, entry)
    if keep_sales:
        remove = _without_sale(remove)
    ops, note = frozenset(report_ops(report)), reason or REPORT_UNDO_REASON
    for c in sorted(remove, key=lambda e: order(e, last), reverse=True):
        if c.kind in ROW_KINDS:
            op = uuid.uuid4()
            void_herd_tracking(
                c.ref, user, note, op, typed=bool(reason), report_ops=ops, keep_buyer_until=keep_buyer_until
            )
            if grant.inbox_grant is not None:  # void_herd_tracking takes no grant, so its trace is left here
                grant.inbox_grant.trace(op)
        elif c.kind == "death":
            undo = [Undo(c.ref, note, report_ops=ops)]
            execute(
                user,
                rabbit_id,
                lambda ctx, undo=undo: undo,
                grant=ReportGrant(
                    grant.inbox_grant, report_ops=ops, code=grant.code, report=grant.report, herd=grant.herd
                ),
            )
        else:
            (Weight if c.kind == "weight" else Bodyfat).delete_by_id(c.ref)
    added = []
    # Opus 2: the report's sale outside the genebank stays (diff), so the rabbit is in GX1/MX1, where execute lets
    # only an editor in. Its 31/12 measurement goes in directly then, as one is deleted above: the report's right was
    # checked at report level (the herd held it on 31/12), and SetMeasurements logs no command.
    if any(c.kind == "transfer" and c.value[0] in OUTSIDE_GENEBANK_HERDS and c not in remove for c in cur):
        for e in [e for e in add if e.kind in MEASUREMENTS and not _measured(e, rabbit_id)]:
            if e.kind == "weight":
                row = Weight.create(individual=rabbit_id, weight=e.value[0], weight_date=e.date)
            else:
                row = Bodyfat.create(individual=rabbit_id, bodyfat=e.value[0], bodyfat_date=e.date)
            added.append(
                {
                    "individual_id": rabbit_id,
                    "kind": e.kind,
                    "id": row.id,
                    "date": e.date.isoformat(),
                    "value": e.value[0],
                }
            )
        add = [e for e in add if e.kind not in MEASUREMENTS]
    return added + _write(user, rabbit_id, add, herd, report, entry, grant, last)


def _cannot(refusals, detail="Rapporten kan inte skickas."):
    return ArsrapportError(422, detail, refusals=[asdict(refusal) for refusal in refusals])


def _written(rabbit, exc):
    """A refused void or write in Ändra or Dra tillbaka, as the 422 refusal for that rabbit (U8)."""
    return _denied(rabbit, exc.detail if isinstance(exc, HerdTrackingError) else None)


def _mail(kind, herd, user, params, ref):
    """Å7–Å9 to the herd's main member, in the caller's transaction; none without an e-mail address."""
    member = inbox.herd_holder(herd.id)
    if member is not None and member.email:
        enqueue_mail(
            kind,
            "member",
            member.id,
            params,
            ref=ref,
            herd=herd,
            genebank=herd.genebank_id,
            dedupe_key=f"{kind}:{ref[1]}",
            created_by=user.id,  # None for a link
        )


def check_paper(sub, access, on):
    """5.5 rules 1 and 5, for the dry run and Skicka: the body's item is the route's, and the form came by `on`."""
    if sub.paper["inbox_item_id"] != access.item.id:
        raise _bad("inbox_item_id", "Blanketten hör till en annan post i kön.")
    if sub.paper["received_on"] > on:
        raise _bad("received_on", "Mottagningsdagen kan inte vara senare än i dag.")


def _lock_form(access, user, herd):
    """
    5.5 rule 2, under the report's lock: the item locked and checked again as report_access read it, and every
    other document in it done and waiting for no parent, since the queue's step 1 comes before the form (5.8).
    Returns the locked item and its arsblankett documents, the form's pages.
    """
    item = inbox.lock_item(access.item.id)
    inbox.require_handler(item, user)  # its 409 says who holds the item now
    if not _form_item(item, user, herd):
        raise ArsrapportError(409, "Posten kan inte matas in längre. Öppna den i kön.")
    others = item.documents.where(InboxDocument.doc_type != "arsblankett")
    if others.where(InboxDocument.done_at.is_null() | InboxDocument.waiting_for.is_null(False)).exists():
        raise ArsrapportError(409, "Registrera intygen i posten först.")
    return item, list(item.documents.where(InboxDocument.doc_type == "arsblankett").order_by(InboxDocument.id))


def _split_sale(proposed, access, report, rabbit, want, prev, entry, proposal, last, at):
    """
    5.9 for one rabbit Skicka writes: `want` without the sale a proposal carries. A pending proposal that `entry`
    still gives stands (_keeps); any other pending one is taken back. A new sale by a role that may not sell (F1)
    goes to `proposed` as (rabbit, entry, sale), for _propose once the submission exists.
    """
    import utils.sale_proposal as sale_proposal  # pylint: disable=import-outside-toplevel  # it imports this module

    if _keeps(proposal, prev, entry):
        return _without_sale(want)
    if proposal is not None and proposal.state == "foreslagen":
        sale_proposal.retract(proposal, now=at)
    if not access.can_sell:
        add = diff(current(report, rabbit), want, last, prev, entry)[1]
        sale = next((e for e in add if e.kind == "transfer"), None)
        if sale is not None:
            proposed.append((rabbit, entry, sale))
            return _without_sale(want)
    return want


def _propose(report, submission, proposed):
    """
    The submission's proposals, under Skicka's locks. A pending proposal follows the submission: one whose rabbit it
    has no sale for is taken back with its buyer, also a rabbit it leaves out (5.7's ending). A rabbit left out keeps
    its register rows (P39a), but not a sale that waits for a decision. Then the new proposals (_split_sale), and the
    data names the pending proposal behind each sale in place of the buyer, which the receipt reads.
    """
    import utils.sale_proposal as sale_proposal  # pylint: disable=import-outside-toplevel  # it imports this module

    rabbits = submission.data["rabbits"]
    for proposal in sale_proposal.pending(report):
        if (rabbits.get(str(proposal.individual_id)) or {}).get("val") != "sald":
            sale_proposal.retract(proposal, now=submission.created_at)
    for rabbit, entry, sale in proposed:
        to_herd = None if entry.sald["till"] == "utanfor" else Herd.get(Herd.herd == sale.value[0])
        buyer, individual = entry.sald["kopare"], Individual(id=rabbit)
        sale_proposal.propose(report, submission, individual, to_herd=to_herd, buyer=buyer, sale_date=sale.date)
    named = {rabbit: p.id for rabbit, p in _proposals(report).items() if p.state == "foreslagen"}
    sales = [(int(key), entry["sald"]) for key, entry in submission.data["rabbits"].items() if entry.get("sald")]
    if any(rabbit in named for rabbit, _ in sales):
        for rabbit, sald in sales:
            if rabbit in named:
                sald["forslag"] = named[rabbit]
        submission.save(only=[YearlyReportSubmission.data])


def submit(herd, round_, access, user, sub, *, now=None) -> dict:
    """
    Skicka (5.4 points 2–5) in one transaction, under the locks in their order: the same request again gets its
    first receipt; otherwise the revision and check() once more, the report row, each rabbit's writes, the
    submission, the draft deleted and the receipt mail queued. On a submitted report it is Ändra: the same row moves
    on and each changed rabbit gets apply_diff, with Å8 for the mail. Every refusal raises, so nothing stays written.
    On paper (5.5) the item is locked and checked after the retry, the writes go through its InboxGrant, and the
    form's pages are done, their photo purged once the report can no longer be withdrawn, before close_if_done.
    Returns the Receipt.
    """
    if sub.key is None:
        raise _bad("submission_key", "Ange submission_key som ett UUID.")
    at = now or globals()["now"]()  # the parameter hides the module's clock, which the tests patch
    on, year = at.astimezone(STOCKHOLM).date(), round_.report_year
    if access.code is not None:
        sub = without_reason(sub)
    last, digest, paper = date(year, 12, 31), request_hash(sub), access.source == "paper"
    if not access.reads_buyers:  # after the hash, which the route's retry makes before it knows the role
        sub = without_reason(sub)
    same = (YearlyHerdReport.herd == herd.id) & (YearlyHerdReport.round == round_.id)
    with DB_PROXY.atomic():
        round_ = _lock_round(round_)  # the dates check() reads under the locks: a round closed meanwhile is seen
        lock_report(round_, herd)
        _recheck_code(access, herd, on)  # E4 before a retry's receipt too; the paper item's exception is below
        saved = find_submission(sub.key, herd, round_, user, digest)
        if saved is not None:  # before any item gate: a retry after the item closed (Codex 5)
            return receipt(saved)
        if paper:
            check_paper(sub, access, on)
        # the membership before the report row, and the main member and its e-mail read under it, before any write
        membership, member = _lock_matrikel(herd) if paper and sub.paper["matrikel"] is not None else (None, None)
        old_email = member.email if member is not None else None
        report = YearlyHerdReport.select().where(same & (YearlyHerdReport.status == "submitted")).for_update().first()
        draft = _draft(herd, round_)  # K1: its kept buyers are linked again or deleted, under the rabbits' locks
        kept = {int(key): claim["kopare_id"] for key, claim in (_kept_claims(draft.data) if draft else {}).items()}
        ids = sorted(set(sub.rabbits) | set(kept))
        items = _lock_items(ids, access.item.id if paper else None, report, kept.values())
        item, pages = _lock_form(access, user, herd) if paper else (None, [])
        _lock_rabbits(ids, items)
        if sub.revision != (report.revision if report else None):
            raise ArsrapportError(409, "Rapporten har ändrats.")
        refusals, _ = check(herd, round_, access, report, sub, on=on)
        if refusals:
            raise _cannot(refusals)
        grant = ReportGrant(
            inbox.InboxGrant(item, user, pages[0]) if paper else None, code=access.code, report=report, herd=herd
        )
        added, change, proposed = [], report is not None, []
        if change:  # Ändra (D5): the same row, and each changed rabbit gets the diff of the report's effects
            before = _entries(_submissions(report)[-1].data.get("rabbits") or {})
            rows = {row["id"]: row for row in report_list(herd, year, report)}
            proposals = _proposals(report)
            report.source, report.report_date, report.revision = access.source, on, report.revision + 1
            report.data = json.dumps(sub.report)
            if paper:
                report.entered_by, report.inbox_item_id = user.id, access.item.id
            elif access.code is not None:
                report.access_code_id = access.code.id
            elif report.generated_by_id is None:  # the first login submission sets it; nothing clears it
                report.generated_by = user.id
            report.save()
            for rabbit, entry in sorted(sub.rabbits.items()):
                prev, proposal = before.get(rabbit), proposals.get(rabbit)
                if entry == prev:  # P39a: an unchanged choice writes nothing
                    continue
                want = wanted(entry, rows[rabbit], report, herd, year, on)
                want = _split_sale(proposed, access, report, rabbit, want, prev, entry, proposal, last, at)
                try:
                    added += apply_diff(
                        report, herd, user, grant, rabbit, want, before.get(rabbit), entry, last, reason=sub.reason
                    )
                except (IndividualRefused, HerdTrackingError) as exc:
                    raise _cannot([_written(rabbit, exc)]) from exc
        else:
            revision = YearlyHerdReport.select(fn.MAX(YearlyHerdReport.revision)).where(same).scalar() or 0
            voided = same & (YearlyHerdReport.status == "voided")
            received = YearlyHerdReport.select(fn.MIN(YearlyHerdReport.received_at)).where(voided).scalar()
            if paper and received is None:  # 5.5 rule 5: the day the form came, from midnight in Stockholm
                received = datetime.combine(sub.paper["received_on"], datetime.min.time(), STOCKHOLM)
            # Codex 2: the manager's current "i tid" decision, a cleared one too, goes with it as received_at does
            decided = YearlyHerdReport.select().where(voided).order_by(YearlyHerdReport.revision.desc()).first()
            report = YearlyHerdReport.create(
                herd=herd.id,
                round=round_.id,
                report_date=on,
                data=json.dumps(sub.report),
                status="submitted",
                source=access.source,
                generated_by=None if paper or access.code else user.id,
                access_code_id=access.code.id if access.code else None,
                entered_by=user.id if paper else None,
                inbox_item_id=access.item.id if paper else None,
                revision=revision + 1,  # voided rows count too, so an old tab never matches a new row
                received_at=received or at,  # 5.13: the round's first submission
                on_time_override=decided.on_time_override if decided else None,
                on_time_set_by=decided.on_time_set_by_id if decided else None,
            )
            rows = {row["id"]: row for row in report_list(herd, year)}
            for rabbit, entry in sorted(sub.rabbits.items()):
                effects = wanted(entry, rows[rabbit], None, herd, year, on)
                effects = _split_sale(proposed, access, None, rabbit, effects, None, entry, None, last, at)
                try:
                    added += _write(user, rabbit, effects, herd, report, entry, grant, last)
                except (IndividualRefused, HerdTrackingError) as exc:
                    raise _cannot([_written(rabbit, exc)]) from exc
        try:
            submission = YearlyReportSubmission.create(
                report=report.id,
                submission_key=sub.key,
                created_at=at,
                source=access.source,
                **_by(user, "user", "access_code"),
                operation_ids=grant.operation_ids,
                added_measurements=added,
                data={**submitted_body(sub), "litters_added": _litters_added(herd, round_)},
                request_hash=digest,
            )
        except IntegrityError as exc:  # the key, taken meanwhile for another herd, which this lock does not cover
            raise ArsrapportError(409, KEY_TAKEN) from exc
        _propose(report, submission, proposed)
        if member is not None:  # check() refused a contact change without one (ingen_huvudmedlem)
            matrikel, signed = sub.paper["matrikel"], sub.paper["signed_on"]
            fields, skipped = apply_paper_matrikel(herd, membership, member, submission, item, user, matrikel, signed)
            log_and_mail_paper_contact(herd, item, submission, user, member, fields, skipped, old_email)
        for page in pages:  # every page of the form; the photo goes once the report cannot be withdrawn (fråga 31)
            page.done_at, page.purge_after = page.done_at or at, at + timedelta(days=WITHDRAW_DAYS)
            page.save()
        if paper:  # after the writes: InboxGrant needs the item "tagen"
            inbox.close_if_done(item, user)
        drop_kept_buyers(set(kept.values()), user)  # FB6: the draft goes, and a kept buyer not linked again with it
        YearlyReportDraft.delete().where(
            (YearlyReportDraft.herd == herd.id) & (YearlyReportDraft.round == round_.id)
        ).execute()
        kind = "arsrapport.andrad" if change else "arsrapport.kvitto"
        _mail(kind, herd, user, {"submission_id": submission.id}, ("yearly_report_submission", submission.id))
        return receipt(submission)


def _pruned(data, choosing, listed):
    """
    FB1: a withdrawn report's draft without what Skicka would refuse now (okand_kanin, senare_handelse): the entries
    of rabbits not left to choose (`choosing`, ids as text) and the defects of rabbits off the list (`listed`), in the
    body and in the form's copy.
    """

    def prune(body):
        if isinstance(body.get("rabbits"), dict):
            body = {**body, "rabbits": {key: e for key, e in body["rabbits"].items() if key in choosing}}
        if isinstance(body.get("defects"), list):
            kept = [d for d in body["defects"] if isinstance(d, dict) and d.get("individual_id") in listed]
            body = {**body, "defects": kept}
        return body

    data = prune(data)
    return {**data, "form": prune(data["form"])} if isinstance(data.get("form"), dict) else data


WITHDRAW_LATE = (
    "Rapporten kan dras tillbaka i 7 dagar efter första inskicket, medan rundan är öppen. Kontakta genbanksansvarig."
)


def withdraw(herd, round_, access, user, *, revision, reason=None, now=None) -> dict:
    """
    Dra tillbaka (fråga 15, 5.13) in one transaction under Skicka's locks: owners and caretakers while the round is
    open and until withdraw_until, editors at any time with a reason, helpers never. Every rabbit the report touched
    loses its current effects as in apply_diff, after one dry run of them all. Pending sale proposals are taken back
    and approved ones stay; for a role that may not sell, so do the sales the report wrote (FB5). The row is voided,
    the draft keeps what was filled in without its key (P31) for the rabbits Skicka takes now (FB1), and Å9 is
    queued. A voided sale's buyer outside the genebank stays until kept_until, and the draft's sale names it (K1,
    K2); a sale the draft no longer has takes its buyer now (FB6). Returns the ReportView.
    """
    import utils.sale_proposal as sale_proposal  # pylint: disable=import-outside-toplevel  # it imports this module

    if access.role == "helper":
        raise ArsrapportError(403, "Genbankshjälpare kan inte dra tillbaka en rapport.")
    reason = _text(reason, "reason") if access.reads_buyers else None  # without_reason
    if access.editor and not reason:
        raise _bad("reason", "Skriv varför rapporten dras tillbaka.")
    at = now or globals()["now"]()  # the parameter hides the module's clock, which the tests patch
    on, last = at.astimezone(STOCKHOLM).date(), date(round_.report_year, 12, 31)
    with DB_PROXY.atomic():
        round_ = _lock_round(round_)  # its end_date as kept_until reads it
        lock_report(round_, herd)
        _recheck_code(access, herd, on)
        report = (
            YearlyHerdReport.select()
            .where(
                (YearlyHerdReport.herd == herd.id)
                & (YearlyHerdReport.round == round_.id)
                & (YearlyHerdReport.status == "submitted")
            )
            .for_update()
            .first()
        )
        if report is None or revision != report.revision:
            raise ArsrapportError(409, "Rapporten har ändrats.")
        submissions = _submissions(report)
        until = withdraw_until(report, access)
        if not access.editor and not (round_open(round_, herd.genebank_id, on) and at <= until):
            raise ArsrapportError(403, WITHDRAW_LATE, withdraw_until=_iso(until))
        # every rabbit of every submission: one an unchanged later submission left out keeps its effects (P39a)
        rabbits = sorted({int(key) for submission in submissions for key in submission.data.get("rabbits") or {}})
        _lock_rabbits(rabbits, _lock_items(rabbits, report=report))
        ops = {str(op) for submission in submissions for op in submission.operation_ids}
        refusals, sold = _reason_refusals(reason, rabbits, _waiting_buyers(sale_proposal.pending(report))), []
        for rabbit in rabbits:
            remove = diff(current(report, rabbit), [], last)[0]
            if not access.can_sell:  # FB5: a sale the owner registered stays, as an approved proposal does
                remove = _without_sale(remove)
            sold += [e.ref for e in remove if e.kind == "transfer"]
            refusals += _register_refusals(rabbit, None, remove, [], ops, access.role == "admin")
        if refusals:
            raise _cannot(refusals, "Rapporten kan inte dras tillbaka.")
        grant, keep = ReportGrant(code=access.code, report=report, herd=herd), not access.can_sell
        keep_until = kept_until(round_)
        keep_until = keep_until if keep_until is not None and keep_until > at else None  # none kept after it
        for rabbit in rabbits:
            try:
                apply_diff(
                    report,
                    herd,
                    user,
                    grant,
                    rabbit,
                    [],
                    None,
                    None,
                    last,
                    reason=reason,
                    keep_sales=keep,
                    keep_buyer_until=keep_until,
                )
            except (IndividualRefused, HerdTrackingError) as exc:
                raise _cannot([_written(rabbit, exc)], "Rapporten kan inte dras tillbaka.") from exc
        for proposal in sale_proposal.pending(report):  # 8: pending proposals are taken back, approved ones stay
            sale_proposal.retract(proposal, now=at)
        report.status, report.voided_at, report.void_reason = "voided", at, reason
        for field, value in _by(user, "voided_by_user", "voided_by_access_code_id").items():
            setattr(report, field, value)
        report.save()
        draft, stamp = _draft(herd, round_), at.astimezone(timezone.utc)
        listed = report_list(herd, round_.report_year)  # FB1: only what Skicka takes now
        choosing = {str(row["id"]) for row in listed if row["state"] == "att_valja"}
        kept = {
            str(row.individual_id): {"kopare_id": row.holder_contact_id, "fran_rapport": report.id}
            for row in HerdTracking.select().where(
                HerdTracking.id.in_(sold), HerdTracking.holder_contact.is_null(False)
            )
        }
        # D10: the submission's data is already stored_body
        latest = {k: v for k, v in submissions[-1].data.items() if k != "litters_added"}  # not the form's
        data = _pruned(latest if draft is None else draft.data, choosing, {row["id"] for row in listed})
        data, gone = _with_kept(data, kept)
        drop_kept_buyers(gone, user)  # FB6; Skicka's locks hold the items and the rabbits
        if draft is None:
            YearlyReportDraft.create(
                herd=herd.id,
                round=round_.id,
                data=data,
                updated_at=stamp,
                **_by(user, "updated_by_user", "updated_by_access_code"),
            )
        else:  # the version moves on, so an old tab's autosave cannot bring the key back
            draft.submission_key, draft.updated_at = None, max(stamp, draft.updated_at + timedelta(microseconds=1))
            draft.data = data
            draft.save()
        _mail("arsrapport.angrad", herd, user, {"report_id": report.id}, ("yearlyherdreport", report.id))
    return report_view(herd, round_, access, user)


def _litters_added(herd, round_):
    """
    The litters registered through the report (RegisterLitter) that no earlier submission of the herd in the round
    has listed, for the submission about to be written: read under the report's lock, so a litter written before it is
    in and one written after it is the next one's. Each is a small dict that the receipt prints as it stood.
    """
    year = round_.report_year
    listed = {
        item["id"]
        for (data,) in YearlyReportSubmission.select(YearlyReportSubmission.data)
        .join(YearlyHerdReport)
        .where(YearlyHerdReport.herd == herd.id, YearlyHerdReport.round == round_.id)
        .tuples()
        for item in data.get("litters_added") or ()
    }
    Mother = Individual.alias()
    litters = {
        row["id"]: row
        for row in Breeding.select(
            Breeding.id,
            Breeding.mother,
            Breeding.birth_date,
            Breeding.litter_size,
            Mother.number.alias("mother_number"),
        )
        .join(Mother, on=(Breeding.mother == Mother.id))
        .where(
            Breeding.breeding_herd_id == herd.id,
            Breeding.birth_date.between(date(year, 1, 1), date(year, 12, 31)),
        )
        .dicts()
    }
    # Bounded by the log's index (individual, created_at): the command ran on the doe that was the herd's at the
    # birth, so she has a herd-tracking row here (or was born here) even if the litter's mother was corrected or she
    # was sold since; and it was written in the report year or later. Within that, by the litter the command made.
    herds_rabbits = (
        HerdTracking.select(HerdTracking.individual)
        .where(HerdTracking.herd == herd.id)
        .union(Individual.select(Individual.id).where(Individual.origin_herd == herd.id))
    )
    made = IndividualCommand.select(IndividualCommand.after).where(
        IndividualCommand.individual.in_(herds_rabbits),
        IndividualCommand.created_at >= date(year, 1, 1) - timedelta(days=1),  # a day's margin for the time zone
        IndividualCommand.command == "RegisterLitter",
        IndividualCommand.after["breeding"].in_([str(i) for i in litters]),
    )
    ids = sorted({row.after["breeding"] for row in made} & litters.keys() - listed)
    return [
        {
            "id": i,
            "mother": litters[i]["mother_number"],
            "birth_date": litters[i]["birth_date"].isoformat(),
            "litter_size": litters[i]["litter_size"],
        }
        for i in ids
    ]


def _with_entry(data, key, raw):
    """A draft's body and its form copy with the rabbit's entry `raw`, or without one when `raw` has no choice."""

    def put(body):
        if not isinstance(body.get("rabbits"), dict):
            return body
        rabbits = {k: e for k, e in body["rabbits"].items() if k != key}
        return {**body, "rabbits": rabbits | ({key: raw} if raw["val"] else {})}

    data = put(data)
    return {**data, "form": put(data["form"])} if isinstance(data.get("form"), dict) else data


REJECTED_KVAR = "Försäljningen avvisades"  # S6: the Ej vägd reason of a rabbit a rejection left as Finns kvar


def settle_rejection(report, user, rabbit, then, at):
    """
    S1: the rabbit of a rejected proposal, rewritten in a submission of the manager's on the same report, under the
    caller's locks (report row, items, rabbit), and the revision moved, so a page opened before it gets 409 and never
    proposes the rejected sale again. "kvar" writes what Finns kvar writes through the report's diff, its operations
    in report_ops (FB2), with the entry's weight and hull (a January sale's), else Ej vägd, so the member's row is
    klar and may still get a weight (S6); the register's refusal is a 409 with its reason. "valj_igen" clears the
    entry (FB3). An open draft gets the same entry and a new version.
    """
    herd, round_ = report.herd, report.round
    year, on = round_.report_year, at.astimezone(STOCKHOLM).date()
    last, latest, key = date(year, 12, 31), _submissions(report)[-1], str(rabbit)
    # a January sale's 31/12 weight and hull stay; Ej vägd only without a weight
    prev = (latest.data.get("rabbits") or {}).get(key) or {}
    measured = {name: prev[name] for name in ("vikt", "hull") if prev.get(name) is not None}
    kvar = {"val": "kvar", "ej_vagd": None if "vikt" in measured else REJECTED_KVAR, **measured}
    raw = dict.fromkeys(ENTRY_KEYS) | (kvar if then == "kvar" else {"val": None})  # as submitted_body stores it
    grant, added = ReportGrant(), []
    if then == "kvar":
        entry, before = _entry(key, raw), _entries(latest.data.get("rabbits") or {}).get(rabbit)
        row, ops = next(r for r in report_list(herd, year, report) if r["id"] == rabbit), report_ops(report)
        want = wanted(entry, row, report, herd, year, on)
        remove, add = diff(current(report, rabbit), want, last, before, entry)
        if row["state"] == "via_flytt":
            refusals = [_refusal(rabbit, "senare_handelse")]
        elif row["state"] == "att_valja" and _holder_on(rabbit, last, ops) != herd.id:
            refusals = [_refusal(rabbit, "inte_innehavare")]
        else:  # one already attested outside the report (redan_rapporterad) stays as it is
            refusals = _register_refusals(rabbit, entry, remove, add, ops, user.is_admin)
        if refusals:
            raise ArsrapportError(409, refusals[0].message, code=refusals[0].code)
        try:
            added = apply_diff(report, herd, user, grant, rabbit, want, before, entry, last)
        except (IndividualRefused, HerdTrackingError) as exc:
            refusal = _written(rabbit, exc)
            raise ArsrapportError(409, refusal.message, code=refusal.code) from exc
    YearlyReportSubmission.create(
        report=report.id,
        submission_key=uuid.uuid4(),
        created_at=at,
        source="login",
        user=user.id,
        operation_ids=grant.operation_ids,
        added_measurements=added,
        data={**latest.data, "rabbits": {**(latest.data.get("rabbits") or {}), key: raw}},
        request_hash="",  # no request: nobody retries this key
    )
    body = json.loads(report.data)  # the report's not_weighed comes from the entries, as parse_submission makes it
    body["not_weighed"] = {k: v for k, v in (body.get("not_weighed") or {}).items() if k != key}
    body["not_weighed"] |= {key: raw["ej_vagd"]} if raw["ej_vagd"] else {}
    report.revision, report.data = report.revision + 1, json.dumps(body)
    report.save(only=[YearlyHerdReport.revision, YearlyHerdReport.data])
    draft = _draft(herd, round_)
    if draft is not None:  # an Ändra in progress: an old tab's autosave gets the 409 and this draft
        draft.data = _with_entry(draft.data, key, raw)
        draft.updated_at = max(at, draft.updated_at + timedelta(microseconds=1)).astimezone(timezone.utc)
        draft.save()


@mail_kind("arsrapport.andrad", priority=0, category="T")
@mail_kind("arsrapport.kvitto", priority=0, category="T")
def _kvitto(params):
    """
    Å7 and Å8 to the herd's main member: what the submission sent, from its row, so a later mail still says what
    was sent (5.4 point 5). Only end_date is the round's when the mail goes (fråga 32: texts read the round's dates).
    """
    submission = YearlyReportSubmission.get_or_none(YearlyReportSubmission.id == params["submission_id"])
    if submission is None:
        return None
    report = YearlyHerdReport.get_by_id(submission.report_id)
    received = submission.data.get("received_on") if submission.source == "paper" else None
    # Late import: arsrapport_pdf imports this module.
    from utils.arsrapport_pdf import receipt_pdf  # pylint: disable=import-outside-toplevel,cyclic-import

    return {
        "attachments": [("kvittens.pdf", "application/pdf", receipt_pdf(report, submission))],
        "herd": report.herd.herd,
        "datum": received or f"{submission.created_at.astimezone(STOCKHOLM):%Y-%m-%d}",
        **receipt(submission)["summary"],
        "kullar": [
            f"efter {item['mother']} född {item['birth_date']}, {item['litter_size']} födda"
            for item in submission.data.get("litters_added") or ()
        ],
        "end_date": f"{report.round.end_date:%Y-%m-%d}",
    }


@mail_kind(A23, priority=0, category="T")
def _kontakt_andrad(params):
    """
    Å23 to the member: which details a paper form changed, the account by its last two digits as they are when the
    mail goes (params hold only ids and flags).
    """
    submission = YearlyReportSubmission.get_or_none(YearlyReportSubmission.id == params["submission_id"])
    if submission is None:
        return None
    herd = YearlyHerdReport.get_by_id(submission.report_id).herd
    flags = {field: bool(params.get(field)) for field in PAPER_FIELDS}
    # The answer the form wrote, read from its own consent row, so the mail can say Ja or Nej (Jonas 2026-11-15).
    change = (
        PublicationConsentChange.select()
        .where(PublicationConsentChange.submission_id == submission.id)
        .order_by(PublicationConsentChange.id.desc())
        .first()
    )
    value = change.value if change is not None and flags["publicering"] else {}
    ja = bool(value.get("name"))
    left_out = [label for key, label in CONSENT_LABELS.items() if ja and not value.get(key)]
    utan = " och ".join([", ".join(left_out[:-1]), left_out[-1]] if len(left_out) > 1 else left_out)
    return {"herd": herd.herd, "account_end": account_end(herd), **flags, "ja": ja, "utan": utan.capitalize()}


@recipient_kind("email_change_old")
def _old_address(request_id):
    """The old address of a member_change_request e-mail change (step 5's link path reuses it)."""
    request = MemberChangeRequest.get_or_none(MemberChangeRequest.id == request_id)
    if request is None:
        return None
    member = Member.get_by_id(request.member_id)
    return Recipient(request.value["old"], f"{member.first_name} {member.last_name}")


@mail_kind("arsrapport.angrad", priority=0, category="T")
def _angrad(params):
    """Å9 to the herd's main member: the report was withdrawn, on the day it was voided."""
    report = YearlyHerdReport.get_or_none(YearlyHerdReport.id == params["report_id"])
    if report is None or report.voided_at is None:
        return None
    return {"herd": report.herd.herd, "datum": f"{report.voided_at.astimezone(STOCKHOLM):%Y-%m-%d}"}


@mail_kind("arsrapport.forsaljning_avvisad", priority=1, category="T")
def _forsaljning_avvisad(params):
    """F4, to the herd's main member: the sale proposal was rejected, with its reason; `kvar` says how it ended."""
    proposal = SaleProposal.get_or_none(SaleProposal.id == params["proposal_id"])
    if proposal is None or proposal.state != "avvisad":
        return None
    rabbit, report = proposal.individual, proposal.report
    return {
        "number": rabbit.number,
        "name": rabbit.name or "",
        "herd": report.herd.herd,
        "reason": proposal.reason,
        "kvar": bool(params.get("kvar")),
        "year": report.round.report_year,
    }


@mail_kind("arsrapport.kop_godkant", priority=1, category="T")
def _kop_godkant(params):
    """FB4, to the buyer herd's main member: a sale on or before 31/12 was approved after the buyer's report came in."""
    proposal = SaleProposal.get_or_none(SaleProposal.id == params["proposal_id"])
    if proposal is None or proposal.state != "godkand":
        return None
    return {"number": proposal.individual.number, "datum": f"{proposal.sale_date:%Y-%m-%d}"}


def stale_link_retry(key, herd, round_):
    """
    The retry of a link's submission by a later code of the same herd (a reissue): the old code is revoked, so the
    answer is 403 `lank_ogiltig` and not the 409 of a key that is someone else's. Returns when it is not that case.
    """
    saved = (
        YearlyReportSubmission.select(YearlyReportSubmission, YearlyHerdReport)
        .join(YearlyHerdReport)
        .where(YearlyReportSubmission.submission_key == key, YearlyReportSubmission.access_code.is_null(False))
        .first()
    )
    if saved is not None and (saved.report.herd_id, saved.report.round_id) == (herd.id, round_.id):
        require_valid_code(saved.access_code_id, herd)


# Kullar under Y (step 4b, Task 2): a litter is written at once, as the report's own writes are not (spec 5.8)

LITTER_KEYS = ("mother_id", "father_id", "birth_date", "litter_size", "litter_size6w")


def _litter_counts(body, new):
    """The body's counts: `litter_size` (born) and `litter_size6w`, which may be null, a preliminary count."""
    counts = {}
    for key in ("litter_size", "litter_size6w"):
        if key not in body:
            if key == "litter_size" and new:
                raise _bad(key, "Ange antal födda.")
            continue
        value = body[key]
        if not (_is_int(value) or (value is None and key == "litter_size6w")):
            raise _bad(key, "Ange antalet som ett heltal.")
        counts[key] = value
    return counts


def _litter_body(body, *, new):
    """A POST (`new`) or PATCH body as the wrappers take it; a PATCH takes only the counts."""
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka kullen som JSON.")
    _keys(body, LITTER_KEYS if new else ("litter_size", "litter_size6w"), "kull")
    fields = _litter_counts(body, new)
    if new:
        for key in ("mother_id", "father_id"):
            if not _is_int(body.get(key)):
                raise _bad(key, "Välj kaninen.")
            fields[key] = body[key]
        fields["birth_date"] = _day(body.get("birth_date"), "birth_date")
    return fields


def _litter_refused(exc):
    """The command's refusal as the report's problem: 409 `samma_kull` with the litter, 403, 404 or a 422."""
    message = exc.envelope.get("message") or "Kullen kan inte sparas."
    if isinstance(exc, SameLitter):
        return ArsrapportError(409, message, code="samma_kull", breeding_id=exc.envelope["breeding_id"])
    if message == "Forbidden":
        return ArsrapportError(403, "Du har inte rätt att ändra kullar i besättningen.")
    if message == "Individual not found":
        return ArsrapportError(404, "Kaninen finns inte.")
    if message.startswith("Kullen finns inte"):
        return ArsrapportError(404, message)
    if message == LITTER_CHANGED:
        return ArsrapportError(409, message)
    return ArsrapportError(422, message)


def require_round_open(herd, round_, access):
    """
    The round open for a write from the report that is not the report itself (a litter, a rabbit, a photo): an editor
    or a helper also after its last day, as Skicka; otherwise 409 rundan_stangd. Returns today.
    """
    on = today()
    activated = _activations(round_).where(YearlyReportRoundGenebank.genebank == herd.genebank_id).exists()
    if not (round_open(round_, herd.genebank_id, on) or ((access.editor or access.role == "helper") and activated)):
        raise ArsrapportError(409, "Rundan är inte öppen.", code="rundan_stangd")
    return on


PHOTO_NOT_OURS = "Fotot hör inte till den här rapporten. Ladda upp det igen."
PHOTO_USED = "Fotot gäller redan en annan kanin. Ladda upp ett nytt foto av intyget."
PHOTO_GONE = "Fotot kan inte användas längre. Ladda upp det igen."


def report_photo_document(item, herd):
    """
    The document of a photo uploaded through the report (…/foto, G5) in `item`, which the caller has locked: the
    herd's own, bound to nothing yet, and one the queue can still check (scrapped, retyped, dismissed or with its
    original gone, it is no longer). The rabbit's registration and the purchase notice bind it under these rules.
    """
    if (item.herd_id, item.kind, item.ref_type) != (herd.id, "kontroll", "individual"):
        raise ArsrapportError(403, PHOTO_NOT_OURS, field="photo")
    if item.ref_id is not None:
        raise ArsrapportError(409, PHOTO_USED, field="photo")
    document = item.documents.order_by(InboxDocument.id).first()
    if (
        item.state in inbox.CLOSED_STATES
        or document is None
        or (document.doc_type, document.done_at) != ("intyg", None)
        or document.original_path is None
    ):
        raise ArsrapportError(409, PHOTO_GONE, field="photo")
    return document


def _litter_write(herd, round_, access, user, write):
    """
    Runs `write(grant)` under the report's lock, as a report writes: the round row read under its lock and open (an
    editor or a helper also after its last day, as Skicka), the link's code read again (E4), a paper item locked and
    checked. It never touches the report row, so a litter moves no `received_at`.
    """
    with DB_PROXY.atomic():
        round_ = _lock_round(round_)  # first, as Skicka: a round closed meanwhile is read here
        on = require_round_open(herd, round_, access)
        lock_report(round_, herd)
        _recheck_code(access, herd, on)
        paper = access.item is not None
        item, pages = _lock_form(access, user, herd) if paper else (None, [])
        report = current_report(herd, round_)
        grant = ReportGrant(
            inbox.InboxGrant(item, user, pages[0]) if paper else None, code=access.code, report=report, herd=herd
        )
        try:
            return write(grant)
        except IndividualRefused as exc:
            raise _litter_refused(exc) from exc


def add_litter(herd, round_, access, user, body):
    """POST kull: a litter without a certificate in the herd; the new litter's id and the year's litters."""
    fields = _litter_body(body, new=True)

    def write(grant):
        litter = register_litter(
            user,
            fields["mother_id"],
            fields["father_id"],
            fields["birth_date"],
            fields["litter_size"],
            fields.get("litter_size6w"),
            herd.herd,
            year=round_.report_year,
            grant=grant,
        )
        mail_added(herd, user, "breeding", litter.id)
        return litter

    litter = _litter_write(herd, round_, access, user, write)
    return {"id": litter.id, "litters": report_litters(herd, round_.report_year)}


ADDED_KINDS = {"breeding": "arsrapport.ny_kull", "individual": "arsrapport.ny_kanin"}


def mail_added(herd, user, ref_type, ref_id):
    """
    Spec 5.8: the receipt of a litter or a rabbit added through the report, whoever added it, to the herd's main member
    as the report's own receipts go, in the addition's transaction and once per addition.
    """
    _mail(ADDED_KINDS[ref_type], herd, user, {f"{ref_type}_id": ref_id}, (ref_type, ref_id))


@mail_kind("arsrapport.ny_kull", priority=0, category="T")
def _ny_kull(params):
    """The receipt of a litter added through the report: the herd, the mother and the birth date as they stand."""
    litter = Breeding.get_or_none(Breeding.id == params["breeding_id"])
    if litter is None or litter.mother_id is None or litter.birth_date is None:
        return None
    return {
        "herd": litter.breeding_herd_id.herd,
        "mother": litter.mother.number,
        "birth_date": litter.birth_date.isoformat(),
    }


@mail_kind("arsrapport.ny_kanin", priority=0, category="T")
def _ny_kanin(params):
    """The receipt of a rabbit added through the report from its certificate: the herd and the rabbit's number."""
    rabbit = Individual.get_or_none(Individual.id == params["individual_id"])
    if rabbit is None or rabbit.voided:
        return None
    return {"herd": rabbit.origin_herd.herd, "number": rabbit.number}


def change_litter(herd, round_, access, user, breeding_id, body):
    """PATCH kull/<id>: the counts of one of the herd's litters, confirmed or changed (a certified one is refused)."""
    fields = _litter_body(body, new=False)
    if "litter_size6w" not in fields:
        raise _bad("litter_size6w", "Ange antal levande vid 6 veckor, eller lämna tomt.")
    year = round_.report_year
    litter = Breeding.get_or_none(Breeding.id == breeding_id)
    if litter is None or litter.breeding_herd_id.id != herd.id or (litter.birth_date or date.min).year != year:
        raise ArsrapportError(404, "Kullen finns inte i besättningens rapport.")
    _litter_write(
        herd,
        round_,
        access,
        user,
        lambda grant: confirm_litter_size(
            user,
            litter.id,
            fields["litter_size6w"],
            year=year,
            grant=grant,
            litter_size=fields.get("litter_size"),
            herd=herd.herd,
        ),
    )
    return {"id": litter.id, "litters": report_litters(herd, year)}


def report_fathers(herd, year):
    """
    The father picker: the herd's genebank's males that lived in `year` or in the longest gestation before it, since
    a litter of early January was mated in December (id, number, name), for a code session too, which has no use of
    the logged-in searches. Nothing else about them.
    """
    mated_from = date(year, 1, 1) - timedelta(days=MAX_GESTATION_DAYS)
    males = (
        Individual.select(Individual.id, Individual.number, Individual.name)
        .join(Herd, on=(Individual.origin_herd == Herd.id))
        .where(
            Herd.genebank == herd.genebank_id,
            Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS),
            Individual.sex == "male",  # a castrated male too: the register accepts him as a father
            not_voided(),
            Individual.death_date.is_null(True) | (Individual.death_date >= mated_from),
        )
        .order_by(Individual.number)
    )
    return [{"id": row["id"], "number": row["number"], "name": row["name"]} for row in males.dicts()]


def report_mothers(herd, year):
    """
    The mother picker, for a code session too: the herd's does at any time in `year` (id, number, name), those sold
    or dead since included, since a litter of May can be added in the autumn; not a doe that left the herd before
    the year. The command still checks the doe's holder on the birth date.
    """
    first, last = date(year, 1, 1), date(year, 12, 31)
    rows = HerdTracking.select(HerdTracking.individual).where(ht_not_voided())
    # in the herd at some time in the year: a row here during it, or the herd as holder on 1 January
    during = rows.where(HerdTracking.herd == herd.id, HerdTracking.herd_tracking_date.between(first, last))
    ever_here = rows.where(HerdTracking.herd == herd.id)
    holder = latest_ht_per_individual(as_of=first).where(HerdTracking.individual.in_(ever_here)).alias("holder")
    on_first = Individual.select(Individual.id).join(
        holder, on=((holder.c.i_id == Individual.id) & (holder.c.rank == 1))
    )
    on_first = on_first.where(holder.c.herd == herd.id)
    # no row by 1 January: the origin herd holds her then, and until her first row, as the command's fallback
    tracked = rows.where(HerdTracking.individual == Individual.id, HerdTracking.herd_tracking_date <= first)
    untracked = (Individual.origin_herd == herd.id) & ~fn.EXISTS(tracked)
    does = (
        Individual.select(Individual.id, Individual.number, Individual.name)
        .where(
            Individual.sex == "female",
            not_voided(),
            Individual.id.in_(during) | Individual.id.in_(on_first) | untracked,
            Individual.death_date.is_null(True) | (Individual.death_date >= first),
        )
        .order_by(Individual.number)
    )
    return [{"id": row["id"], "number": row["number"], "name": row["name"]} for row in does.dicts()]


def report_parent(herd, number):
    """
    The registration form's lookup by number (4b, L10), for a code session too: a rabbit of the herd's genebank, with
    what the form compares against the photo (name, colour, parents), and a doe's litters born in this herd, which
    fill in the kit's litter. None for any other number, so a link learns nothing outside its genebank.
    """
    rabbit = Individual.get_or_none((Individual.number == number) & not_voided())
    if rabbit is None or rabbit.origin_herd.genebank_id != herd.genebank_id:
        return None
    litter = rabbit.breeding

    def named(parent):
        return {"number": parent.number, "name": parent.name} if parent is not None else None

    litters = (
        Breeding.select()
        .where(Breeding.mother == rabbit.id, Breeding.breeding_herd_id == herd.id, Breeding.birth_date.is_null(False))
        .order_by(Breeding.birth_date.desc())
        if rabbit.sex == "female"
        else []
    )
    return {
        "number": rabbit.number,
        "name": rabbit.name,
        "sex": rabbit.sex,
        "color": rabbit.color.name if rabbit.color_id else None,
        "mother": named(litter.mother if litter else None),
        "father": named(litter.father if litter else None),
        "litters": [
            {
                "id": row.id,
                "birth_date": row.birth_date.isoformat(),
                "father": row.father.number if row.father_id else None,
                "litter_size": row.litter_size,
                "litter_size6w": row.litter_size6w,
                "preliminary": row.litter_size6w_preliminary,
            }
            for row in litters
        ],
    }


def genebank_colors(herd):
    """The colour names of the herd's genebank, which the registration accepts (it drops any other name)."""
    return [row.name for row in Color.select(Color.name).where(Color.genebank == herd.genebank_id).order_by(Color.name)]
