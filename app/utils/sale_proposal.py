"""
Sale proposals (spec section 6, 5.9): a sale that a caretaker or the report link reports, which the genebank's
manager approves or rejects. Each proposal has a `kontroll` item in the queue. The caller holds no lock: the
functions take the report lock and row, then the items, then the rabbit's litter and the rabbit, the order of 5.9.
"""

from datetime import date, datetime
from typing import Literal

from peewee import IntegrityError

import utils.arsrapport as arsrapport
import utils.inbox as inbox
import utils.purchase_notice as purchase_notice
from utils.database import (
    DB_PROXY,
    AuditLog,
    BuyerContact,
    Herd,
    HerdTracking,
    InboxItem,
    SaleProposal,
    YearlyHerdReport,
    ht_not_voided,
    ht_order_desc,
    lock_individuals,
)
from utils.herd_tracking import (
    BUYER_TEXT_FIELDS,
    HerdTrackingError,
    HerdTrackingInvalid,
    _audit_user,
    _reject_buyer_name,
    buyer_contact_fields,
)
from utils.individual_commands import IndividualRefused, lock_individual_for_edit, record_sale

DECIDED = "Förslaget är redan avgjort."
NAMED = "Skriv orsaken utan köparens namn."
BUYER_GONE = "Köparens uppgifter är raderade, så försäljningen kan inte godkännas. Avvisa den i stället."


TICKED = ("contact_consent_at", "membership_optin_at")


def _stored_buyer(buyer, at, *, address_required):
    """
    The buyer as the sale takes it again at approval: the text fields and the two ticks, checked now, and when each
    was ticked (`at`, the submission's time), which approval gives the BuyerContact in place of its own time.
    """
    fields = buyer_contact_fields(buyer, address_required=address_required)
    return {
        **{key: fields[key] for key in BUYER_TEXT_FIELDS},
        "contact_consent": buyer.get("contact_consent", False),
        "membership_optin": buyer.get("membership_optin", False),
        **{key: at.isoformat() for key in TICKED if fields[key]},
    }


def _lock_item(proposal):
    """The proposal's item, locked; None when the queue's purge has deleted it (the decision does not need it)."""
    if proposal.inbox_item_id is None:
        return None
    return InboxItem.select().where(InboxItem.id == proposal.inbox_item_id).for_update().first()


def _close_item(proposal, user, state):
    """The proposal's item is done: "klar" when decided, "skrap" when taken back."""
    item = _lock_item(proposal)
    if item is not None and item.state not in inbox.CLOSED_STATES:
        previous = item.state
        inbox._set_state(item, state)  # pylint: disable=protected-access
        item.save()
        inbox.log_event(item, user, "lage", **{"from": previous, "to": state})


def propose(report, submission, individual, *, to_herd, buyer, sale_date: date, buyer_correction=False) -> SaleProposal:
    """
    A pending sale of `individual` from the report's herd, to `to_herd` or, with None, to a buyer outside the
    genebank (then `buyer` is required). Its `kontroll` item goes to the genebank's queue (F3). The proposer is
    `submission`'s user or access code.
    """
    if (to_herd is None) == (buyer is None):
        raise HerdTrackingInvalid("Ange köparens besättning, eller köparens namn och ort utanför genbanken.")
    at = submission.created_at  # when the seller sent it, and ticked the buyer's boxes
    stored = _stored_buyer(buyer, at, address_required=not buyer_correction) if buyer is not None else None
    with DB_PROXY.atomic():
        try:
            proposal = SaleProposal.create(
                report=report.id,
                submission=submission.id,
                individual=individual.id,
                to_herd=to_herd.id if to_herd is not None else None,
                buyer=stored,
                sale_date=sale_date,
                created_at=at,
            )
        except IntegrityError as exc:  # idx_sale_proposal_open: one open proposal per rabbit and report
            raise arsrapport.ArsrapportError(409, "Kaninen har redan en försäljning som väntar.") from exc
        item = InboxItem.create(
            kind="kontroll",
            state="ny",
            genebank=report.herd.genebank_id,
            herd=report.herd_id,
            ref_type="sale_proposal",
            ref_id=proposal.id,
        )
        proposal.inbox_item_id = item.id
        proposal.save()
        inbox.log_event(item, None, "kom_in")
    return proposal


def pending(report) -> list[SaleProposal]:
    return list(
        SaleProposal.select()
        .where(SaleProposal.report == report.id, SaleProposal.state == "foreslagen")
        .order_by(SaleProposal.id)
    )


def retract(proposal, *, now: datetime) -> None:
    """The member took the sale back: `atertagen`, the buyer deleted, the item closed. A decided proposal stays."""
    with DB_PROXY.atomic():
        arsrapport.lock_report(proposal.report.round, proposal.report.herd)
        arsrapport._lock_items([], report=proposal.report)  # pylint: disable=protected-access  # K4
        changed = (
            SaleProposal.update(state="atertagen", buyer=None, decided_at=now)
            .where(SaleProposal.id == proposal.id, SaleProposal.state == "foreslagen")
            .execute()
        )
        if changed:
            _close_item(proposal, None, "skrap")


def _claim(proposal, user, now, **fields):
    """Takes the decision with UPDATE … WHERE state = 'foreslagen' (section 6): a second decider gets 409."""
    changed = (
        SaleProposal.update(decided_by=user.id, decided_at=now, buyer=None, **fields)
        .where(SaleProposal.id == proposal.id, SaleProposal.state == "foreslagen")
        .execute()
    )
    if not changed:
        raise arsrapport.ArsrapportError(409, DECIDED)


def _locked(proposal, buyer=False):
    """
    The report lock, the report row, then the report's item set in one ascending pass (K4): the rabbit's buyer items
    and every pending proposal's item, this one's too. Returns the proposal and its report as they are under them,
    and the ids of the buyer's purchase notices that the sale settles.
    With `buyer` the buying herd's report lock too, both in herd id order, the only place that takes two (P2): the
    buyer's Skicka then comes wholly before the approval or after it. A purchase notice of the buyer's may be in
    another year's report, so the purchase's own lock serializes those, and the notices read under it join the item
    pass.
    """
    report = proposal.report
    herds = {report.herd_id} | ({proposal.to_herd_id} if buyer and proposal.to_herd_id else set())
    for herd_id in sorted(herds):
        arsrapport.lock_report(report.round, Herd(id=herd_id))
    report = YearlyHerdReport.select().where(YearlyHerdReport.id == report.id).for_update().get()
    notices = []
    if buyer and proposal.to_herd_id:
        purchase_notice.lock_purchase(proposal.to_herd_id, proposal.individual_id)
        found = purchase_notice.open_notices([proposal.to_herd_id])
        notices = [item.id for item in purchase_notice.matching(proposal, report.herd.herd, found)]
    arsrapport._lock_items([proposal.individual_id], report=report, notices=notices)  # pylint: disable=protected-access
    return SaleProposal.get_by_id(proposal.id), report, notices


def _refused(proposal, exc):
    """The register's refusal of a decision's write, as a 409 with its reason (U8)."""
    refusal = arsrapport._written(proposal.individual_id, exc)  # pylint: disable=protected-access
    return arsrapport.ArsrapportError(409, refusal.message, code=refusal.code)


def approve(proposal, user, *, now: datetime) -> HerdTracking:
    """
    Registers the sale (record_sale, as the manager's or admin's own right, grant=None) and closes the item, also after
    the round's end_date (5.9). A sale on or before 31/12 into a herd whose report is in is mailed to its main member,
    who then changes the report (FB4), while the round is open for it: after end_date only the status flag shows it.
    """
    with DB_PROXY.atomic():
        proposal, report, notices = _locked(proposal, buyer=True)
        if proposal.state != "foreslagen":
            raise arsrapport.ArsrapportError(409, DECIDED)
        if proposal.to_herd_id is None and proposal.buyer is None:  # erased or purged (clear_buyer)
            raise arsrapport.ArsrapportError(409, BUYER_GONE)
        buyer = proposal.buyer
        code = proposal.to_herd.herd if proposal.to_herd_id else arsrapport._sale_code(report.herd, "utanfor")  # pylint: disable=protected-access
        _claim(proposal, user, now, state="godkand")
        lock_individual_for_edit(proposal.individual_id)
        # the sale takes its seller from the latest holder: a move meanwhile must not sell from another herd
        if arsrapport._holder_on(proposal.individual_id, proposal.sale_date, set()) != report.herd_id:  # pylint: disable=protected-access
            raise arsrapport.ArsrapportError(409, arsrapport.REFUSALS["senare_handelse"])
        try:
            record_sale(user, proposal.individual_id, code, proposal.sale_date.isoformat(), buyer=buyer)
        except (IndividualRefused, HerdTrackingError) as exc:
            raise _refused(proposal, exc) from exc
        row = (
            HerdTracking.select()
            .where(
                HerdTracking.individual == proposal.individual_id,
                HerdTracking.kind == "TRANSFER",
                ht_not_voided(),
            )
            .order_by(*ht_order_desc())
            .first()
        )
        ticked = {key: datetime.fromisoformat(buyer[key]) for key in TICKED if buyer and buyer.get(key)}
        if ticked:  # the consent dates from the seller's tick, not from the approval
            BuyerContact.update(**ticked).where(BuyerContact.id == row.holder_contact_id).execute()
        SaleProposal.update(herd_tracking_id=row.id).where(SaleProposal.id == proposal.id).execute()
        _close_item(proposal, user, "klar")
        for item_id in notices:  # fråga 19: one approval settles the buyer's notice too
            purchase_notice.close(item_id, user)
        buyer_report = arsrapport.current_report(proposal.to_herd, report.round) if proposal.to_herd_id else None
        day = now.astimezone(arsrapport.STOCKHOLM).date()
        if (
            buyer_report is not None
            and proposal.sale_date <= date(report.round.report_year, 12, 31)
            and arsrapport.round_open(report.round, proposal.to_herd.genebank_id, day)  # the mail asks for a change
        ):
            ref = ("sale_proposal", proposal.id)
            arsrapport._mail("arsrapport.kop_godkant", proposal.to_herd, user, {"proposal_id": proposal.id}, ref)  # pylint: disable=protected-access
    return row


def reject(proposal, user, *, reason: str, then: Literal["kvar", "valj_igen"], now: datetime) -> None:
    """
    F4: `avvisad` with a reason, which may not name the buyer (K6). The rabbit's entry is rewritten in a submission of
    the manager's (S1): "kvar" writes Finns kvar, attesting it on 31/12 unless that is there (FB2), and "valj_igen"
    leaves it to choose again (FB3). A refused attestation leaves the proposal open. The member is mailed the reason.
    """
    if then not in ("kvar", "valj_igen"):
        raise arsrapport.ArsrapportError(400, "Välj om kaninen finns kvar eller om medlemmen ska välja igen.")
    reason = arsrapport._text(reason, "reason")  # pylint: disable=protected-access  # 400 for a phone or an e-mail
    if not reason:
        raise arsrapport.ArsrapportError(400, "Skriv varför försäljningen inte godkänns.", field="reason")
    with DB_PROXY.atomic():
        proposal, report, _ = _locked(proposal)
        if proposal.state != "foreslagen":
            raise arsrapport.ArsrapportError(409, DECIDED)
        names = [proposal.buyer["name"]] if proposal.buyer else ()
        try:
            _reject_buyer_name([reason], [proposal.individual_id], names=names)
        except HerdTrackingInvalid as exc:
            raise arsrapport.ArsrapportError(400, NAMED, field="reason") from exc
        _claim(proposal, user, now, state="avvisad", reason=reason)
        lock_individual_for_edit(proposal.individual_id)
        arsrapport.settle_rejection(report, user, proposal.individual_id, then, now)
        _close_item(proposal, user, "klar")
        params, ref = {"proposal_id": proposal.id, "kvar": int(then == "kvar")}, ("sale_proposal", proposal.id)
        arsrapport._mail("arsrapport.forsaljning_avvisad", report.herd, user, params, ref)  # pylint: disable=protected-access


def clear_buyer(proposal, action, user=None, still=None) -> int:
    """
    The pending proposal's buyer goes (spec section 6), under a decision's locks: the report lock and row, the
    report's items (_locked), then the rabbit, with `still` (SQL), the rule that chose it, read again under them. One
    audit_log row without the buyer, as for a BuyerContact. Returns 1 when it went, else 0. A sale outside the
    genebank without its buyer can only be rejected (BUYER_GONE).
    """
    with DB_PROXY.atomic():
        proposal, _, _ = _locked(proposal)
        lock_individuals([proposal.individual_id])  # a death is read under the rabbit's lock
        query = SaleProposal.update(buyer=None).where(
            SaleProposal.id == proposal.id, SaleProposal.state == "foreslagen", SaleProposal.buyer.is_null(False)
        )
        changed = (query.where(still) if still is not None else query).execute()
        if changed:
            AuditLog.create(
                table_name=SaleProposal._meta.table_name,
                record_id=str(proposal.id),
                operation="UPDATE",
                new_data={"action": action},
                changed_fields=["buyer"],
                changed_by=_audit_user(user) if user is not None else None,
            )
    return changed


def decisions(report) -> list[dict]:
    """
    The status view's sale dialog (5.9), for the genebank's manager or admin: the report's pending proposals, a buyer
    outside the genebank by name and town only, and whether the buyer has reported the purchase (K7), with the buyer
    herd's purchase notice that approving the sale settles (fråga 19), or one whose date does not fit the sale's.
    """
    proposals, seller = pending(report), report.herd.herd
    notices = purchase_notice.open_notices({p.to_herd_id for p in proposals if p.to_herd_id})

    def first(found):
        return purchase_notice.notice_json(found[0]) if found else None

    return [
        {
            "id": proposal.id,
            "individual_id": proposal.individual_id,
            "number": proposal.individual.number,
            "name": proposal.individual.name,
            "to_herd": proposal.to_herd.herd if proposal.to_herd_id else None,
            "buyer": {"name": proposal.buyer.get("name"), "town": proposal.buyer.get("town")}
            if proposal.buyer
            else None,
            "sale_date": proposal.sale_date.isoformat(),
            # without its day in the report (5.3): the date is the month's last day, or the day it was sent
            "day_known": not arsrapport.dayless(proposal.submission.data, proposal.individual_id, "sald"),
            "buyer_notified_at": proposal.buyer_notified_at.isoformat() if proposal.buyer_notified_at else None,
            "kopanmalan": first(purchase_notice.matching(proposal, seller, notices)),
            # M1: the buyer's notice of the same purchase with a date too far off or across 31/12, shown with a warning
            "kopanmalan_avviker": first(purchase_notice.mismatched(proposal, seller, notices)),
        }
        for proposal in proposals
    ]
