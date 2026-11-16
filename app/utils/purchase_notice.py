"""
Purchase notices (step 4a Task 5, fråga 19): the buyer reports a rabbit bought during the report's year that Stamboken
has not moved into the herd. A notice is a `kontroll` item of the buyer herd, its fields in `ref_data` (the number,
the seller herd's code, the date and the rabbit's id) and no personal data. The genebank's manager registers the
transfer, or approves the seller's matching sale proposal, and the notice closes once a transfer of the rabbit into
the herd is registered by any path.
"""

import datetime
from collections import Counter
from datetime import timedelta

import utils.arsrapport as arsrapport
import utils.inbox as inbox
from utils.arsrapport import ArsrapportError
from utils.database import (
    DB_PROXY,
    Herd,
    HerdTracking,
    InboxItem,
    Individual,
    SaleProposal,
    YearlyHerdReport,
    coerce_date,
    current_holder_row,
    ht_not_voided,
    not_voided,
)
from utils.report_code import CodeActor

KIND = "kopanmalan"
MATCH_DAYS = 14  # mitt val: a notice and a sale proposal of the same rabbit this close in date are one sale
NOT_IN_STAMBOKEN = "Finns kaninen inte i Stamboken? Lägg till den från intyget."
REGISTERED = "Köpet är registrerat"


def _day(item):
    return datetime.date.fromisoformat(item.ref_data["date"])


def notice_json(item):
    """ReportView.kopanmalningar's row: the notice's fields and the item's state."""
    return {"id": item.id, **{key: item.ref_data[key] for key in ("number", "from_herd", "date")}, "state": item.state}


def open_notices(herd_ids):
    """The open notices of the herds, oldest first."""
    query = InboxItem.select().where(
        InboxItem.herd.in_(sorted(herd_ids)), InboxItem.ref_type == KIND, InboxItem.state.in_(inbox.OPEN_STATES)
    )
    return list(query.order_by(InboxItem.id))


def report_purchase(herd, round_, actor, *, number, from_herd, date, photo_document_id=None) -> InboxItem:
    """
    The notice that `herd` bought the rabbit `number` from the herd `from_herd` ("utanfor": the genebank's GX1 or
    MX1) on `date`, in the round's year. A number Stamboken lacks is the certificate's form, not a notice; a rabbit
    the herd already holds needs none; an open notice of the same rabbit is the answer again. `actor` is the
    account or the link (CodeActor), which the item's history names.
    """
    # shortcut: no photo field until 4b's report upload is merged into this branch; wire it then
    del photo_document_id
    year = round_.report_year
    individual = None
    if isinstance(number, str):  # as the queue's _live_individual: a voided litter slot is no rabbit
        individual = Individual.get_or_none((Individual.number == number.strip()) & not_voided())
    if individual is None:
        raise ArsrapportError(422, NOT_IN_STAMBOKEN, code="inte_i_stamboken", field="number")
    seller = arsrapport._sale_code(herd, from_herd) if isinstance(from_herd, str) else None  # pylint: disable=protected-access
    if seller is None or seller == herd.herd or Herd.get_or_none(Herd.herd == seller) is None:
        raise ArsrapportError(400, "Välj säljarens besättning, eller Utanför genbanken.", field="from_herd")
    last = min(datetime.date(year, 12, 31), arsrapport.today())
    if not isinstance(date, datetime.date) or not datetime.date(year, 1, 1) <= date <= last:
        raise ArsrapportError(400, f"Ange ett datum under {year}, inte senare än i dag.", field="date")
    by_link = isinstance(actor, CodeActor)
    with DB_PROXY.atomic():
        arsrapport.lock_report(round_, herd)  # an approval holds the buyer's lock: a notice comes before it or after
        if by_link:
            arsrapport.require_valid_code(actor.code.id, herd, lock=True)  # E4 under the lock
        holder = current_holder_row(individual.id)
        if holder is not None and holder.herd_id == herd.id:
            raise ArsrapportError(409, f"{individual.number} står redan i din besättning.", field="number")
        same = [item for item in open_notices([herd.id]) if item.ref_data["individual_id"] == individual.id]
        if same:
            return same[0]
        item = InboxItem.create(
            kind="kontroll",
            state="ny",
            genebank=herd.genebank_id,
            herd=herd.id,
            ref_type=KIND,
            ref_data={
                "number": individual.number,
                "from_herd": seller,
                "date": date.isoformat(),
                "individual_id": individual.id,
            },
        )
        # the link has no account: its name goes in the history, as _audit_as names it to the audit log
        inbox.log_event(item, None if by_link else actor.id, "inkommen", **({"via": actor.username} if by_link else {}))
    return item


def _matches(proposal, seller, item):
    """The pending sale `proposal` from the herd `seller` (a code) is the sale the notice `item` reports."""
    data = item.ref_data
    return (
        proposal.individual_id == data["individual_id"]
        and proposal.to_herd_id == item.herd_id
        and seller == data["from_herd"]
        and abs((proposal.sale_date - _day(item)).days) <= MATCH_DAYS
    )


def matching(proposal, seller, items):
    """The notices among `items` that approving `proposal`, a pending sale from the herd `seller`, settles."""
    return [item for item in items if _matches(proposal, seller, item)]


def _pending_of(individual_ids):
    """The rabbits' pending sale proposals, with their report and seller herd read in the same query."""
    return list(
        SaleProposal.select(SaleProposal, YearlyHerdReport, Herd)
        .join(YearlyHerdReport)
        .join(Herd)
        .where(SaleProposal.individual.in_(sorted(individual_ids)), SaleProposal.state == "foreslagen")
        .order_by(SaleProposal.id)
    )


def proposal_for(item):
    """The pending sale proposal the notice `item` matches, or None."""
    proposals = _pending_of([item.ref_data["individual_id"]])
    return next((p for p in proposals if _matches(p, p.report.herd.herd, item)), None)


def registered(items):
    """
    The ids of the notices among `items` whose transfer is registered: an active TRANSFER of the rabbit into the
    buyer herd, registered after the notice came in or dated at most MATCH_DAYS before the notice's date. One older
    in both is an earlier stay in the herd, as for a rabbit bought back.
    """
    if not items:
        return set()
    columns = (HerdTracking.individual, HerdTracking.herd, HerdTracking.herd_tracking_date, HerdTracking.created_at)
    rows = HerdTracking.select(*columns).where(
        HerdTracking.individual.in_(sorted({item.ref_data["individual_id"] for item in items})),
        HerdTracking.herd.in_(sorted({item.herd_id for item in items})),
        HerdTracking.kind == "TRANSFER",
        ht_not_voided(),
    )
    moves = [(row.individual_id, row.herd_id, coerce_date(row.herd_tracking_date), row.created_at) for row in rows]
    return {
        item.id
        for item in items
        if any(
            (rabbit, herd) == (item.ref_data["individual_id"], item.herd_id)
            and (day >= _day(item) - timedelta(days=MATCH_DAYS) or (made is not None and made >= item.received_at))
            for rabbit, herd, day, made in moves
        )
    }


def close(item_id, user):
    """The notice is done, "Köpet är registrerat", under its lock; a closed or purged one is left as it is."""
    item = InboxItem.select().where(InboxItem.id == item_id).for_update().first()
    if item is not None and item.state not in inbox.CLOSED_STATES:
        previous = item.state
        inbox._set_state(item, "klar")  # pylint: disable=protected-access
        item.save()
        inbox.log_event(item, user, "lage", **{"from": previous, "to": "klar", "note": REGISTERED})


def close_registered(items):
    """
    Self-closing without a trigger: each open notice among `items` whose transfer is registered, each in a
    transaction of its own that takes only the item's lock. Idempotent.
    """
    for item_id in sorted(registered([item for item in items if item.ref_type == KIND])):
        with DB_PROXY.atomic():
            close(item_id, None)


def report_notices(herd, year):
    """ReportView.kopanmalningar: the herd's notices dated in `year`, after the registered ones are closed."""
    close_registered(open_notices([herd.id]))
    query = InboxItem.select().where(InboxItem.herd == herd.id, InboxItem.ref_type == KIND).order_by(InboxItem.id)
    return [notice_json(item) for item in query if _day(item).year == year]


def unsettled(herd_ids, year):
    """
    The status view's kop_anmalt per herd: open notices dated in `year`, neither registered nor matched by a pending
    sale proposal. A matched one is shown with its sale in the seller's sale dialog.
    """
    items = [item for item in open_notices(herd_ids) if _day(item).year == year]
    done = registered(items)
    proposals = _pending_of({item.ref_data["individual_id"] for item in items}) if items else []
    return Counter(
        item.herd_id
        for item in items
        if item.id not in done and not any(_matches(p, p.report.herd.herd, item) for p in proposals)
    )
