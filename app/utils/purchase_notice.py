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
    HOLDER_CHANGING_KINDS,
    Herd,
    HerdTracking,
    InboxItem,
    Individual,
    SaleProposal,
    YearlyHerdReport,
    coerce_date,
    current_holder_row,
    ht_not_voided,
    lock_individuals,
    not_voided,
)

KIND = "kopanmalan"
_PURCHASE_LOCK = 0x48424B50  # "HBKP": classid of the advisory lock on a purchase of a rabbit into a herd
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


def lock_purchase(herd_id, individual_id):
    """
    The advisory lock on a purchase of the rabbit into the herd, whatever year's report it is in: a notice's creation
    and the approval of a sale into the herd take it after their report locks, code row and report row, and before
    any item, so a notice comes wholly before the approval that settles it or after (fråga 19).
    """
    DB_PROXY.execute_sql(
        "SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (_PURCHASE_LOCK, f"{herd_id}/{individual_id}")
    )


def report_purchase(herd, round_, access, user, *, number, from_herd, date, photo_document_id=None) -> InboxItem:
    """
    The notice that `herd` bought the rabbit `number` from the herd `from_herd` ("utanfor": the genebank's GX1 or
    MX1) on `date`, in the round's year. A number Stamboken lacks is the certificate's form, not a notice; a rabbit
    the herd already holds needs none; an open notice of the same rabbit is the answer again, and one of another year
    a 409. The rabbit and the seller are looked up in the herd's genebank only, so another genebank's existing
    number or herd is answered as a missing one. Written as the report is, while the round is open (`access`);
    `user` is the account or the link (CodeActor), which the item's history names.
    """
    # shortcut: no photo field until 4b's report upload is merged into this branch; wire it then
    del photo_document_id
    year = round_.report_year
    individual = None
    if isinstance(number, str):  # as the queue's _live_individual: a voided litter slot is no rabbit
        individual = (
            Individual.select()
            .join(Herd, on=(Individual.origin_herd == Herd.id))
            .where(Individual.number == number.strip(), not_voided(), Herd.genebank == herd.genebank_id)
            .first()
        )
    if individual is None:
        raise ArsrapportError(422, NOT_IN_STAMBOKEN, code="inte_i_stamboken", field="number")
    seller = arsrapport._sale_code(herd, from_herd) if isinstance(from_herd, str) else None  # pylint: disable=protected-access
    sellers = Herd.select().where(Herd.herd == seller, Herd.genebank == herd.genebank_id)
    if seller is None or seller == herd.herd or not sellers.exists():
        raise ArsrapportError(400, "Välj säljarens besättning, eller Utanför genbanken.", field="from_herd")
    last = min(datetime.date(year, 12, 31), arsrapport.today())
    if not isinstance(date, datetime.date) or not datetime.date(year, 1, 1) <= date <= last:
        raise ArsrapportError(400, f"Ange ett datum under {year}, inte senare än i dag.", field="date")
    by_link = access.code is not None
    with DB_PROXY.atomic():
        arsrapport.lock_report(round_, herd)
        if by_link:
            arsrapport.require_valid_code(access.code.id, herd, lock=True)  # E4 under the lock
        arsrapport.require_open(round_, herd, access, arsrapport.today())
        lock_purchase(herd.id, individual.id)  # an approval of the sale settles the notice, whatever its year
        holder = current_holder_row(individual.id)
        if holder is not None and holder.herd_id == herd.id:
            raise ArsrapportError(409, f"{individual.number} står redan i din besättning.", field="number")
        same = [item for item in open_notices([herd.id]) if item.ref_data["individual_id"] == individual.id]
        other = next((item for item in same if _day(item).year != year), None)
        if other is not None:  # the link of one year neither answers with nor writes past another year's notice
            raise ArsrapportError(
                409, f"Köpet av {individual.number} är redan anmält för {_day(other).year}.", field="number"
            )
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
        inbox.log_event(item, None if by_link else user.id, "inkommen", **({"via": user.username} if by_link else {}))
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


def _order(row):
    """The register's order, oldest first (ht_order_desc reversed): a day's BIRTH first, then write order."""
    return coerce_date(row.herd_tracking_date), row.kind != "BIRTH", row.id


def registered(items):
    """
    The ids of the notices among `items` whose transfer is registered: an active TRANSFER of the rabbit into the
    buyer herd, registered after the notice came in or dated at most MATCH_DAYS before the notice's date, after
    which no active row moves the rabbit to another herd on or before that date. One that a later move ended before
    the purchase is an earlier stay in the herd, also when it was registered after the notice, as for a rabbit bought
    back. A pure read: the closing calls it again under the locks.
    """
    if not items:
        return set()
    rows = list(
        HerdTracking.select().where(
            HerdTracking.individual.in_(sorted({item.ref_data["individual_id"] for item in items})),
            HerdTracking.kind.in_(HOLDER_CHANGING_KINDS),
            ht_not_voided(),
        )
    )

    def bought(item, move):
        day, rabbit = _day(item), item.ref_data["individual_id"]
        recent = coerce_date(move.herd_tracking_date) >= day - timedelta(days=MATCH_DAYS)
        if not recent and (move.created_at is None or move.created_at < item.received_at):
            return False
        return not any(
            row.individual_id == rabbit
            and row.herd_id != item.herd_id
            and _order(move) < _order(row)
            and coerce_date(row.herd_tracking_date) <= day
            for row in rows
        )

    return {
        item.id
        for item in items
        if any(
            move.kind == "TRANSFER"
            and (move.individual_id, move.herd_id) == (item.ref_data["individual_id"], item.herd_id)
            and bought(item, move)
            for move in rows
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
    Self-closing without a trigger: each open notice among `items` whose transfer is registered. The caller holds
    the items' locks. The rabbits are locked after them, the queue's order (item, then rabbit), and the transfer read
    again under them, so a void or correction of it, which locks the rabbit first, comes wholly before that read or
    after the closing. Idempotent.
    """
    notices = [item for item in items if item.ref_type == KIND and item.state in inbox.OPEN_STATES]
    if not registered(notices):  # a look without the rabbits' locks first, so most opened items take none
        return
    lock_individuals({item.ref_data["individual_id"] for item in notices})
    for item_id in sorted(registered(notices)):
        close(item_id, None)


def report_notices(herd, round_, access):
    """
    ReportView.kopanmalningar: the herd's notices dated in the round's year, after the registered ones among them are
    closed. Only that year's notices, which `access` reaches; the closing writes under the report's lock, and a link
    only while it is valid (E4).
    """
    year = round_.report_year

    def of_year(items):
        return [item for item in items if _day(item).year == year]

    mine = of_year(open_notices([herd.id]))
    if registered(mine):  # only then the locks
        with DB_PROXY.atomic():
            arsrapport.lock_report(round_, herd)
            if access.code is not None:
                arsrapport.require_valid_code(access.code.id, herd, lock=True)
            locked = InboxItem.select().where(InboxItem.id.in_([item.id for item in mine])).order_by(InboxItem.id)
            close_registered(list(locked.for_update()))
    query = InboxItem.select().where(InboxItem.herd == herd.id, InboxItem.ref_type == KIND).order_by(InboxItem.id)
    return [notice_json(item) for item in of_year(query)]


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
