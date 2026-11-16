"""
Sale proposals (spec section 6, 5.9): a sale that a caretaker or the report link reports, which the genebank's
manager approves or rejects. Each proposal has a `kontroll` item in the queue. The caller holds no lock: the
functions take the report lock, then the item, then the rabbit's (execute does), the order of 5.9.
"""

from datetime import date, datetime
from typing import Literal

from peewee import IntegrityError

import utils.arsrapport as arsrapport
import utils.inbox as inbox
from utils.database import DB_PROXY, HerdTracking, InboxItem, SaleProposal, ht_not_voided, ht_order_desc
from utils.herd_tracking import (
    BUYER_TEXT_FIELDS,
    HerdTrackingInvalid,
    _reject_buyer_name,
    buyer_contact_fields,
    require_reason,
)
from utils.individual_commands import RecordAttestation, execute, lock_individual_for_edit, record_sale

DECIDED = "Förslaget är redan avgjort."
NAMED = "Skriv orsaken utan köparens namn."


def _stored_buyer(buyer):
    """The buyer as the sale takes it again at approval: the text fields and the two ticks, checked now."""
    buyer_contact_fields(buyer)  # contact only with the tick (ADR-0016)
    return {
        **{key: buyer.get(key) for key in BUYER_TEXT_FIELDS},
        "contact_consent": buyer.get("contact_consent", False),
        "membership_optin": buyer.get("membership_optin", False),
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


def propose(report, submission, individual, *, to_herd, buyer, sale_date: date) -> SaleProposal:
    """
    A pending sale of `individual` from the report's herd, to `to_herd` or, with None, to a buyer outside the
    genebank (then `buyer` is required). Its `kontroll` item goes to the genebank's queue (F3). The proposer is
    `submission`'s user or access code.
    """
    if (to_herd is None) == (buyer is None):
        raise HerdTrackingInvalid("Ange köparens besättning, eller köparens namn och ort utanför genbanken.")
    stored = _stored_buyer(buyer) if buyer is not None else None
    with DB_PROXY.atomic():
        try:
            proposal = SaleProposal.create(
                report=report.id,
                submission=submission.id,
                individual=individual.id,
                to_herd=to_herd.id if to_herd is not None else None,
                buyer=stored,
                sale_date=sale_date,
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


def _locked(proposal):
    """
    The report lock, then the report's item set in one ascending pass (K4): the rabbit's buyer items and every pending
    proposal's item, this one's too. Returns the proposal as it is under them.
    """
    report = proposal.report
    arsrapport.lock_report(report.round, report.herd)
    arsrapport._lock_items([proposal.individual_id], report=report)  # pylint: disable=protected-access
    return SaleProposal.get_by_id(proposal.id)


def approve(proposal, user, *, now: datetime) -> HerdTracking:
    """Registers the sale (record_sale, as the manager's or admin's own right, grant=None) and closes the item."""
    with DB_PROXY.atomic():
        proposal = _locked(proposal)
        if proposal.state != "foreslagen":
            raise arsrapport.ArsrapportError(409, DECIDED)
        report, buyer = proposal.report, proposal.buyer
        code = proposal.to_herd.herd if proposal.to_herd_id else arsrapport._sale_code(report.herd, "utanfor")  # pylint: disable=protected-access
        _claim(proposal, user, now, state="godkand")
        lock_individual_for_edit(proposal.individual_id)
        # the sale takes its seller from the latest holder: a move meanwhile must not sell from another herd
        if arsrapport._holder_on(proposal.individual_id, proposal.sale_date, set()) != report.herd_id:  # pylint: disable=protected-access
            raise arsrapport.ArsrapportError(409, arsrapport.REFUSALS["senare_handelse"])
        record_sale(user, proposal.individual_id, code, proposal.sale_date.isoformat(), buyer=buyer)
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
        SaleProposal.update(herd_tracking_id=row.id).where(SaleProposal.id == proposal.id).execute()
        _close_item(proposal, user, "klar")
    return row


def reject(proposal, user, *, reason: str, then: Literal["kvar", "valj_igen"], now: datetime) -> None:
    """
    F4: `avvisad` with a reason (without the buyer's name, K6). "kvar" attests the rabbit on 31/12 as the manager,
    unless it already has that attestation; "valj_igen" leaves it unchosen. A refused attestation leaves the
    proposal open.
    """
    if then not in ("kvar", "valj_igen"):
        raise arsrapport.ArsrapportError(400, "Välj om kaninen finns kvar eller om medlemmen ska välja igen.")
    with DB_PROXY.atomic():
        proposal = _locked(proposal)
        if proposal.state != "foreslagen":
            raise arsrapport.ArsrapportError(409, DECIDED)
        reason = require_reason(reason)
        names = [proposal.buyer["name"]] if proposal.buyer else ()
        try:
            _reject_buyer_name([reason], [proposal.individual_id], names=names)
        except HerdTrackingInvalid as exc:
            raise arsrapport.ArsrapportError(400, NAMED) from exc
        report = proposal.report
        _claim(proposal, user, now, state="avvisad", reason=reason)
        # shortcut: no manager submission in report_ops and no cleared choice (FB2, FB3): 4a Task 2/3 completes it
        if then == "kvar":
            lock_individual_for_edit(proposal.individual_id)  # execute locks too, but not when already attested
            last = date(report.round.report_year, 12, 31)
            attested = HerdTracking.select().where(
                HerdTracking.individual == proposal.individual_id,
                HerdTracking.kind == "ATTESTATION",
                HerdTracking.herd_tracking_date == last,
                HerdTracking.herd == report.herd_id,
                ht_not_voided(),
            )
            if not attested.exists():
                if arsrapport._holder_on(proposal.individual_id, arsrapport.today(), set()) != report.herd_id:  # pylint: disable=protected-access
                    raise arsrapport.ArsrapportError(409, arsrapport.REFUSALS["senare_handelse"])
                command = RecordAttestation(report.herd.herd, last.isoformat(), report=report.id)
                execute(user, proposal.individual_id, lambda ctx: [command])
        _close_item(proposal, user, "klar")
