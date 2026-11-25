"""
Purchase notices (step 4a Task 5, fråga 19): the buyer reports a rabbit bought during the report's year that Stamboken
has not moved into the herd. A notice is a `kontroll` item of the buyer herd, its fields in `ref_data` (the number,
the seller herd's code, the date and the rabbit's id) and no personal data, and maybe a photo of the transfer proof
or the certificate, a document kept and purged as the queue's are. The genebank's manager registers the
transfer, or approves the seller's matching sale proposal, and the notice closes once a transfer of the rabbit into
the herd is registered by any path, dated within 14 days of the notice and with no 31/12 between them.

A rabbit Stamboken lacks is no notice (S7): the buyer sends the photos of its certificate and transfer proof to the
queue as an ordinary upload of the herd, with the purchase's fields in `ref_data`, and the manager or a helper
registers it in its birth herd and transfers it; the queue closes the upload, and the report shows it as registered
once that transfer is.
The report lists its herd's queue items in plain words (S8, report_cases).
"""

import datetime
import hashlib
import json
from collections import Counter

import utils.arsrapport as arsrapport
import utils.inbox as inbox
import utils.inbox_interpreter as interpreter
from utils.arsrapport import ArsrapportError
from utils.database import (
    DB_PROXY,
    HOLDER_CHANGING_KINDS,
    Herd,
    HerdTracking,
    InboxDocument,
    InboxItem,
    Individual,
    SaleProposal,
    YearlyHerdReport,
    YearlyReportRound,
    coerce_date,
    current_holder_row,
    ht_not_voided,
    lock_individuals,
    not_voided,
)
from utils.individual_number_v2 import parse_number
from utils.matrikel import resolve_own_membership
from utils.report_code import actor_key, invitation_recipient

KIND = "kopanmalan"
_PURCHASE_LOCK = 0x48424B50  # "HBKP": classid of the advisory lock on a purchase of a rabbit into a herd
MATCH_DAYS = 14  # mitt val: a notice and a sale proposal of the same rabbit this close in date are one sale
NOT_IN_STAMBOKEN = (  # S7: the dialog then sends the photos (send_photos)
    "Kaninen finns inte i Stamboken än. Skicka foto av intyget, och av försäljningsbeviset om du har det. "
    "Genbanksansvarig registrerar kaninen och för över den till dig."
)
BEVIS_FROM_YEAR = 2027
PHOTO_TYPES = ("bevis", "intyg")  # what a notice's photo shows: the transfer proof, or the rabbit's certificate
REGISTERED = "Köpet är registrerat"
MAX_PHOTOS = 2  # S7: the certificate, and the transfer proof if the buyer has it
PHOTO_REQUIRED = "Ladda upp ett foto av intyget eller försäljningsbeviset."
CASE_DAYS = 14  # S8: a closed item stays in the report's list this long


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


def open_sent(herd_ids):
    """The herds' open uploads of sent photos (S7), oldest first."""
    query = InboxItem.select().where(
        InboxItem.herd.in_(sorted(herd_ids)),
        InboxItem.kind == "upload",
        InboxItem.ref_data.is_null(False),
        InboxItem.state.in_(inbox.OPEN_STATES),
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


def _locked_photo(herd, document, photos, notice):
    """
    The photo's item and the open `notice` (or None) locked in one ascending pass after the purchase lock, the queue's
    order, and the photo checked under it as a rabbit's is (FC1): uploaded through the report in this session
    (`photos`, their items) and bound to nothing yet. Returns the photo's item and the notice, None if it has closed.
    """
    if document is None or document.item_id not in photos:  # a missing photo answers as another's does
        raise ArsrapportError(403, arsrapport.PHOTO_NOT_OURS, field="photo")
    ids = sorted({document.item_id} | ({notice.id} if notice is not None else set()))
    locked = {
        item.id: item for item in InboxItem.select().where(InboxItem.id.in_(ids)).order_by(InboxItem.id).for_update()
    }
    photo = locked.get(document.item_id)
    if photo is None or arsrapport.report_photo_document(photo, herd).id != document.id:
        raise ArsrapportError(409, arsrapport.PHOTO_GONE, field="photo")
    notice = locked.get(notice.id) if notice is not None else None
    return photo, notice if notice is not None and notice.state not in inbox.CLOSED_STATES else None


def _in_genebank(number, genebank_id):
    """The live rabbit `number` born in the genebank, or None: as the queue's _live_individual, a voided slot is not."""
    return (
        Individual.select()
        .join(Herd, on=(Individual.origin_herd == Herd.id))
        .where(Individual.number == number, not_voided(), Herd.genebank == genebank_id)
        .first()
    )


def _seller(herd, year, from_herd, date):
    """
    The seller herd's code for `from_herd` ("utanfor": the genebank's GX1 or MX1), another herd of the herd's genebank,
    with `date` checked to fall in the round's `year` and not after today.
    """
    seller = arsrapport._sale_code(herd, from_herd) if isinstance(from_herd, str) else None  # pylint: disable=protected-access
    sellers = Herd.select().where(Herd.herd == seller, Herd.genebank == herd.genebank_id)
    if seller is None or seller == herd.herd or not sellers.exists():
        raise ArsrapportError(400, "Välj säljarens besättning, eller Utanför genbanken.", field="from_herd")
    last = min(datetime.date(year, 12, 31), arsrapport.today())
    if not isinstance(date, datetime.date) or not datetime.date(year, 1, 1) <= date <= last:
        raise ArsrapportError(400, f"Ange ett datum under {year}, inte senare än i dag.", field="date")
    return seller


def _check_photo_type(doc_type, year):
    if year < BEVIS_FROM_YEAR:
        if doc_type != "intyg":
            raise ArsrapportError(400, "Ladda upp ett foto av intyget.", field="doc_type")
    elif doc_type not in PHOTO_TYPES:
        raise ArsrapportError(400, "Välj om fotot visar försäljningsbeviset eller intyget.", field="doc_type")


def report_purchase(
    herd, round_, access, user, *, number, from_herd, date, photo_document_id=None, doc_type=None, photos=()
) -> InboxItem:
    """
    The notice that `herd` bought the rabbit `number` from the herd `from_herd` ("utanfor": the genebank's GX1 or
    MX1) on `date`, in the round's year. A number Stamboken lacks is the certificate's form, not a notice; a rabbit
    the herd already holds needs none; an open notice of the same rabbit is the answer again, and one of another year
    a 409. The rabbit and the seller are looked up in the herd's genebank only, so another genebank's existing
    number or herd is answered as a missing one. Written as the report is, while the round is open (`access`);
    `user` is the account or the link (CodeActor), which the item's history names; the notice's `member` is the
    link's member or the account's person, who sent it.

    `photo_document_id` is a photo of the transfer proof or the certificate (`doc_type` "bevis" or "intyg") that this
    session uploaded through the report (`photos`, its items). It moves to the notice, and its own item goes; the same
    request again answers with the notice. The queue's workers hear of a notice once, when its first photo comes.
    """
    year = round_.report_year
    individual = _in_genebank(number.strip().upper(), herd.genebank_id) if isinstance(number, str) else None
    if individual is None:
        detail = (
            "Kaninen finns inte i Stamboken än. Skicka foto av intyget. "
            "Genbanksansvarig registrerar kaninen och för över den till dig."
            if year < BEVIS_FROM_YEAR
            else NOT_IN_STAMBOKEN
        )
        raise ArsrapportError(422, detail, code="inte_i_stamboken", field="number")
    seller = _seller(herd, year, from_herd, date)
    if photo_document_id is not None:
        _check_photo_type(doc_type, year)
    by_link = access.code is not None
    with DB_PROXY.atomic():
        # The round row first, as Dra tillbaka takes it: an end_date moved meanwhile is read here, not the one before
        round_ = arsrapport._lock_round(round_)  # pylint: disable=protected-access
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
        item, photo = same[0] if same else None, None
        if photo_document_id is not None:
            document = InboxDocument.get_or_none(InboxDocument.id == photo_document_id)
            if item is not None and document is not None and document.item_id == item.id:
                return item  # the photo is already this notice's: the same request again
            photo, item = _locked_photo(herd, document, photos, item)
        elif item is not None:
            return item
        first = item is None or not item.documents.exists()  # the queue hears of a notice with its first photo
        if item is None:
            item = InboxItem.create(
                kind="kontroll",
                state="ny",
                genebank=herd.genebank_id,
                herd=herd.id,
                # who sent it: the link's member or the account's person, whom an erasure finds
                member=access.code.member_id if by_link else resolve_own_membership(user),
                ref_type=KIND,
                ref_data={
                    "number": individual.number,
                    "from_herd": seller,
                    "date": date.isoformat(),
                    "individual_id": individual.id,
                },
            )
        # the link has no account: its name and code go in the history, as _audit_as names it to the audit log
        detail = {"via": user.username, "access_code_id": access.code.id} if by_link else {}
        if photo is not None:
            # not read by the model: the queue saves nothing from a notice, a reading claimed before the move drops, and
            # one made before it goes
            read = dict.fromkeys(("interpretation", "proposal", "interpreter", "interpreted_at"))
            moved = InboxDocument.update(item=item.id, doc_type=doc_type, interpretation_status="av", **read)
            moved.where(InboxDocument.id == photo_document_id).execute()
            InboxItem.delete().where(InboxItem.id == photo.id).execute()  # the photo's own item, empty now
            detail["documents"] = 1
        inbox.log_event(item, None if by_link else user.id, "inkommen", **detail)
        if photo is not None and first:
            inbox._notify_workers(item, None if by_link else user)  # pylint: disable=protected-access
    return item


def sent(item):
    """Photos of a rabbit Stamboken lacks, sent through the report (S7): an upload with the purchase's fields."""
    return item.kind == "upload" and item.ref_data is not None


def _photo_list(documents, year):
    """The body's [{id, doc_type}]: one or two distinct photos, each a certificate ("intyg") or a proof ("bevis")."""
    if (
        not isinstance(documents, list)
        or not 1 <= len(documents) <= MAX_PHOTOS
        or not all(isinstance(d, dict) and type(d.get("id")) is int for d in documents)  # True is an int too
        or len({d["id"] for d in documents}) != len(documents)
    ):
        detail = "Ladda upp ett foto av intyget." if year < BEVIS_FROM_YEAR else PHOTO_REQUIRED
        raise ArsrapportError(400, detail, field="photo")
    for document in documents:
        _check_photo_type(document.get("doc_type"), year)
    return {d["id"]: d["doc_type"] for d in documents}


def send_photos(herd, round_, access, user, *, number, from_herd, date, documents, photos=()) -> InboxItem:
    """
    S7: the rabbit `number`, bought from `from_herd` on `date` and not in Stamboken, sent to the queue as photos of its
    certificate and transfer proof (`documents`, [{id, doc_type}]) that this session uploaded through the report
    (`photos`, their items). As if the buyer had mailed them: an ordinary upload of the herd (`kind` "upload", no
    ref_type, so the queue registers and transfers from it), its certificates read as usual, the purchase's fields in
    `ref_data`, and the queue's workers told once. Written as a notice is, while the round is open; `user` is the
    account or the link, which the item's history names, and a link's item has the member it went to as `member`. The
    same request again, by the same actor from the session that uploaded the photos and for the same year, answers
    with the item (its receipt); any other runs every check.
    """
    year = round_.report_year
    number = number.strip().upper() if isinstance(number, str) else ""
    if not number or parse_number(number) is None:
        raise ArsrapportError(400, "Skriv kaninens individnummer, till exempel G1234-2501.", field="number")
    if _in_genebank(number, herd.genebank_id) is not None:  # a rabbit Stamboken has is a notice
        raise ArsrapportError(409, f"{number} finns i Stamboken. Anmäl köpet i stället.", field="number")
    seller = _seller(herd, year, from_herd, date)
    types = _photo_list(documents, year)
    by_link = access.code is not None
    canonical = [*actor_key(user), herd.id, year, number, seller, date.isoformat(), sorted(types.items())]
    request = hashlib.sha256(json.dumps(canonical).encode()).hexdigest()
    with DB_PROXY.atomic():
        round_ = arsrapport._lock_round(round_)  # pylint: disable=protected-access
        arsrapport.lock_report(round_, herd)  # also two sends of the herd's report, one after the other
        if by_link:
            arsrapport.require_valid_code(access.code.id, herd, lock=True)  # E4 under the lock
        arsrapport.require_open(round_, herd, access, arsrapport.today())
        found = list(InboxDocument.select().where(InboxDocument.id.in_(sorted(types))))
        held = sorted({document.item_id for document in found})
        if len(found) == len(types) and len(held) == 1:  # maybe the same request again: the item they went to
            item = InboxItem.get_or_none(InboxItem.id == held[0])  # a purge may have taken it since
            receipt = item.ref_data.get("receipt") if item is not None and sent(item) else None
            # its receipt: this actor, herd, year and payload, from photos this session uploaded (photos keeps them)
            if receipt and receipt["request"] == request and set(receipt["staged"]) <= set(photos):
                return item
        if len(found) != len(types) or any(item_id not in photos for item_id in held):  # missing is not ours
            raise ArsrapportError(403, arsrapport.PHOTO_NOT_OURS, field="photo")
        # each photo's own item locked in one ascending pass, the queue's order, and checked under it (FC1)
        locked = {i.id: i for i in InboxItem.select().where(InboxItem.id.in_(held)).order_by(InboxItem.id).for_update()}
        for document in found:
            staged = locked.get(document.item_id)
            # only a photo held for sending (PURPOSES) moves: a plain report photo may be in reading
            if (
                staged is None
                or (staged.ref_data or {}).get(inbox.PURPOSE) not in inbox.PURPOSES
                or arsrapport.report_photo_document(staged, herd).id != document.id
            ):
                raise ArsrapportError(409, arsrapport.PHOTO_GONE, field="photo")
        item = InboxItem.create(
            kind="upload",
            genebank=herd.genebank_id,
            herd=herd.id,
            sender_user=None if by_link else user.id,
            # who sent it: the link's member (its mails go there, an erasure finds it), or the account's person
            member=access.code.member_id if by_link else resolve_own_membership(user),
            ref_data={
                "number": number,
                "from_herd": seller,
                "date": date.isoformat(),
                "receipt": {"staged": held, "request": request},
            },
        )
        # read as any upload's certificate: a reading claimed before the move drops (attempts), one made before it goes
        read = dict.fromkeys(("interpretation", "proposal", "interpreter", "interpreted_at"))
        for document_id, doc_type in types.items():
            status = interpreter.initial_status() if doc_type == "intyg" else "av"
            moved = InboxDocument.update(
                item=item.id, doc_type=doc_type, interpretation_status=status, attempts=0, **read
            )
            moved.where(InboxDocument.id == document_id).execute()
        InboxItem.delete().where(InboxItem.id.in_(held)).execute()  # the photos' own items, empty now
        # the link has no account: its name and code go in the history, as a report photo's code does
        detail = {"via": user.username, "access_code_id": access.code.id} if by_link else {}
        inbox.log_event(item, None if by_link else user.id, "inkommen", documents=len(types), **detail)
        inbox._notify_workers(item, None if by_link else user)  # pylint: disable=protected-access
    return item


def _fits(moved, item):
    """
    A sale or transfer on `moved` is the purchase the notice `item` reports by date: at most MATCH_DAYS apart and no
    31/12 between them (within 14 days, the same year), so a rabbit counted on one 31/12 is never another's purchase.
    """
    day = _day(item)
    return abs((moved - day).days) <= MATCH_DAYS and moved.year == day.year


def _same_purchase(proposal, seller, item):
    """The pending sale `proposal` from the herd `seller` (a code) has the rabbit, seller and buyer of `item`."""
    data = item.ref_data
    return (
        proposal.individual_id == data["individual_id"]
        and proposal.to_herd_id == item.herd_id
        and seller == data["from_herd"]
    )


def _matches(proposal, seller, item):
    """The pending sale `proposal` from the herd `seller` is the sale the notice `item` reports."""
    return _same_purchase(proposal, seller, item) and _fits(proposal.sale_date, item)


def matching(proposal, seller, items):
    """The notices among `items` that approving `proposal`, a pending sale from the herd `seller`, settles."""
    return [item for item in items if _matches(proposal, seller, item)]


def mismatched(proposal, seller, items):
    """The notices among `items` of the purchase `proposal` sells whose date does not fit it: approval leaves them."""
    return [item for item in items if _same_purchase(proposal, seller, item) and not _fits(proposal.sale_date, item)]


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


def _rabbits(items):
    """
    {item id: the rabbit's id} for the notices and sent photos among `items`: a notice's own rabbit, and for sent
    photos the live rabbit their number names in the item's genebank, once Stamboken has it.
    """
    rabbits = {item.id: item.ref_data["individual_id"] for item in items if not sent(item)}
    wanted = [item for item in items if sent(item)]
    if wanted:
        query = (
            Individual.select(Individual.number, Herd.genebank, Individual.id)
            .join(Herd, on=(Individual.origin_herd == Herd.id))
            .where(Individual.number.in_(sorted({item.ref_data["number"] for item in wanted})), not_voided())
        )
        found = {(number, genebank): rabbit for number, genebank, rabbit in query.tuples()}
        for item in wanted:
            if (key := (item.ref_data["number"], item.genebank_id)) in found:
                rabbits[item.id] = found[key]
    return rabbits


def registered(items):
    """
    The ids of the notices and sent photos among `items` whose transfer is registered: an active TRANSFER of the
    rabbit into the buyer herd whose date fits the notice's (_fits), after which no active row moves the rabbit to
    another herd on or before that date. One that a later move ended before the purchase is an earlier stay in the
    herd, also when it was registered after the notice, as for a rabbit bought back. Any other transfer leaves the
    notice open, for the manager to close by hand. A pure read: the closing calls it again under the locks.
    """
    rabbits = _rabbits(items) if items else {}
    if not rabbits:
        return set()
    rows = list(
        HerdTracking.select().where(
            HerdTracking.individual.in_(sorted(set(rabbits.values()))),
            HerdTracking.kind.in_(HOLDER_CHANGING_KINDS),
            ht_not_voided(),
        )
    )

    def bought(item, move):
        day, rabbit = _day(item), rabbits[item.id]
        if not _fits(coerce_date(move.herd_tracking_date), item):
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
        if item.id in rabbits
        and any(
            move.kind == "TRANSFER"
            and (move.individual_id, move.herd_id) == (rabbits[item.id], item.herd_id)
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
    after the closing. Idempotent. Sent photos (S7) are an ordinary upload, which only the queue closes.
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


def _case_state(item, waiting, done):
    """
    S8's state in plain words: closed; sent photos whose transfer is registered (`done`), which the queue closes; a
    photo still to be read; waiting for the manager; or someone has it.
    """
    if item.state in inbox.CLOSED_STATES:
        return "klart"
    if item.id in done:
        return "registrerad"
    if item.state == "ny":
        return "tolkas" if item.id in waiting else "vantar"
    return "arbetar"  # held, handed on, or a question out: Mina inskick's under_arbete and fragat


def report_cases(herd, year):
    """
    ReportView.arenden (S8): the queue items that concern the herd's report, in plain words, open ones first, a closed
    one for CASE_DAYS after it closed. What came through the report (photos sent, and its kontroll items: sale
    proposals, purchase notices and the photos of rabbits added from it), and an ordinary upload its recipient sent:
    the member recorded when it came in, or for an older one without, the recipient's account. Never through a right to
    the herd, which a later grant or revoke would change. A purchase or a sale of another year is left out. A row holds
    no message, no other sender's item and no buyer. A few queries, whatever the number of items.
    """
    since = inbox.now() - datetime.timedelta(days=CASE_DAYS)
    kontroll = (InboxItem.kind == "kontroll") & (
        InboxItem.ref_type.in_(("sale_proposal", KIND))
        | ((InboxItem.ref_type == "individual") & InboxItem.ref_id.is_null(False))  # a photo not yet bound is no case
    )
    items = list(
        InboxItem.select().where(
            InboxItem.herd == herd.id,
            kontroll | (InboxItem.kind == "upload"),
            InboxItem.closed_at.is_null() | (InboxItem.closed_at >= since),
        )
    )
    recipient = invitation_recipient(herd)  # the member the herd's report goes to now

    def from_recipient(item):
        if recipient is None:
            return False
        if item.member_id is not None:
            return item.member_id == recipient.id
        return recipient.user_id is not None and item.sender_user_id == recipient.user_id  # an older upload

    items = [
        item
        for item in items
        if (item.kind == "kontroll" or sent(item) or from_recipient(item))
        and (item.ref_data is None or _day(item).year == year)
    ]
    ids = [item.id for item in items]
    photos, waiting = Counter(), set()
    documents = InboxDocument.select(InboxDocument.item, InboxDocument.interpretation_status, InboxDocument.done_at)
    for item_id, status, done in documents.where(InboxDocument.item.in_(ids)).tuples():
        photos[item_id] += 1
        if status == "vantar" and done is None:
            waiting.add(item_id)
    proposals = [item.ref_id for item in items if item.ref_type == "sale_proposal"]
    sales = dict(
        SaleProposal.select(SaleProposal.id, Individual.number)
        .join(Individual)
        .switch(SaleProposal)
        .join(YearlyHerdReport)
        .join(YearlyReportRound)
        .where(SaleProposal.id.in_(proposals), YearlyReportRound.report_year == year)
        .tuples()
    )
    bound = [item.ref_id for item in items if item.ref_type == "individual"]
    numbers = dict(Individual.select(Individual.id, Individual.number).where(Individual.id.in_(bound)).tuples())
    done = registered([item for item in items if sent(item) and item.state in inbox.OPEN_STATES])

    def row(item):
        if item.ref_type == "sale_proposal":
            what, number = "forsaljning", sales[item.ref_id]
        elif item.ref_type == "individual":
            what, number = "foto", numbers.get(item.ref_id)
        else:
            what = "kopanmalan" if item.ref_type == KIND else "kop_saknas" if sent(item) else "inskick"
            number = item.ref_data["number"] if item.ref_data else None
        state = _case_state(item, waiting, done)
        return {"id": item.id, "what": what, "number": number, "photos": photos[item.id], "state": state}

    rows = [row(item) for item in items if item.ref_type != "sale_proposal" or item.ref_id in sales]
    return sorted(rows, key=lambda r: (r["state"] == "klart", -r["id"]))


def unsettled(herd_ids, year):
    """
    The status view's kop_anmalt per herd: open notices and sent photos (S7) dated in `year`, not registered, and a
    notice not matched by a pending sale proposal either. A matched one is shown with its sale in the seller's sale
    dialog; sent photos are of a rabbit Stamboken lacked, which no proposal sells.
    """
    items = [item for item in open_notices(herd_ids) if _day(item).year == year]
    uploads = [item for item in open_sent(herd_ids) if _day(item).year == year]
    done = registered(items + uploads)
    proposals = _pending_of({item.ref_data["individual_id"] for item in items}) if items else []
    return Counter(
        item.herd_id
        for item in items + uploads
        if item.id not in done and (sent(item) or not any(_matches(p, p.report.herd.herd, item) for p in proposals))
    )
