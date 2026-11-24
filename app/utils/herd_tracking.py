"""
Herd-tracking domain service.

Every write to herd_tracking goes through this module: it locks the individual
row, validates the invariants and groups rows into operations. data_access.py
imports this module; this module never imports data_access.py.
"""

import re
import unicodedata
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from peewee import Case, Expression, IntegrityError, fn

from utils import settings
from utils.buyer_mail import queue_buyer_mails
from utils.database import (
    DB_PROXY,
    HOLDER_CHANGING_KINDS,
    OUTSIDE_GENEBANK_HERDS,
    AuditLog,
    Breeding,
    BuyerContact,
    Herd,
    HerdTracking,
    InboxDocument,
    InboxItem,
    Individual,
    IndividualCommand,
    SaleProposal,
    YearlyHerdReport,
    YearlyReportRound,
    YearlyReportSubmission,
    coerce_date,
    ht_not_voided,
    ht_order_desc,
    ht_sort_key,
    lock_individuals,
)
from utils.login_code import lock_addresses
from utils.mail import address_hash, forget_recipient, is_address

UNPROMOTE_REASON = "avpromoverad"
UNDO_REASON = "Ångrad av den som registrerade den"


class HerdTrackingError(ValueError):
    """Domain error with an HTTP status. Subclasses ValueError so legacy callers that catch ValueError keep working."""

    status = 400
    title = "Ogiltig begäran"

    def __init__(self, detail, *, rows=None):
        super().__init__(detail)
        self.detail = detail
        self.rows = rows or []


class HerdTrackingInvalid(HerdTrackingError):
    status, title = 400, "Ogiltig begäran"


class HerdTrackingForbidden(HerdTrackingError):
    status, title = 403, "Åtkomst nekad"


class HerdTrackingNotFound(HerdTrackingError):
    status, title = 404, "Hittades inte"


class HerdTrackingConflict(HerdTrackingError):
    status, title = 409, "Konflikt"


def _now_utc():
    return datetime.now(timezone.utc)


def _sale_midnight(sale_date):
    return datetime.combine(coerce_date(sale_date), datetime.min.time(), ZoneInfo("Europe/Stockholm"))


def _set_buyer_sale_date(contact_id, sale_date):
    optin = BuyerContact.membership_optin_at
    BuyerContact.update(
        purge_at=BuyerContact.purge_at_for(sale_date),
        membership_optin_at=Case(None, [(optin.is_null(False), _sale_midnight(sale_date))], optin),
    ).where(BuyerContact.id == contact_id).execute()


def _buyer_name_key(name):
    return unicodedata.normalize("NFC", name.strip()).casefold()


def _new_buyer(fields, user, sale_date):
    """
    The BuyerContact of a sale outside, five years from its date; None when those have passed: such a buyer is
    never stored (nor mailed), and the sale is written as one whose buyer was removed.
    """
    purge_at = BuyerContact.purge_at_for(sale_date)
    if purge_at <= _now_utc():
        return None
    with DB_PROXY.atomic():
        if email := fields["email"]:
            email = email.strip().lower()
            lock_addresses([email])
            same_address = fn.lower(fn.trim(BuyerContact.email)) == email
            if settings.mail.link_secret:  # the erase link also covers rows whose e-mail has been purged
                same_address |= BuyerContact.erased_email_hash == address_hash(email)
            contacts = BuyerContact.select(BuyerContact.name).where(same_address)
            name = _buyer_name_key(fields["name"])
            if any(_buyer_name_key(contact.name) != name for contact in contacts):
                raise HerdTrackingConflict("E-postadressen finns redan hos en annan köpare. Kontrollera adressen.")
        return BuyerContact.create(**fields, created_by_user=user, purge_at=purge_at)


def new_operation_id(value=None):
    """The caller's operation id (Server Actions send one per dialog), or a fresh one."""
    if value is None or value == "":
        return uuid.uuid4()
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise HerdTrackingInvalid("Ogiltigt operation_id.") from exc


def _void_rows(rows, user, reason, operation_id):
    """
    WHITELISTED in-place UPDATE #1: set the four void fields on still-active rows. Returns the buyers outside the
    association those rows held; the caller passes them to _drop_orphan_buyers once its writes are done.
    """
    ids = [r.id for r in rows]
    if not ids:
        return []
    code_id = getattr(user, "access_code_id", None)  # the report link as the voider (step 3)
    voider = {"voided_by_access_code_id": code_id} if code_id is not None else {"voided_by_user": user}
    voided = list(
        HerdTracking.update(
            voided_at=_now_utc(),
            **voider,
            voided_reason=reason,
            voided_operation_id=operation_id,
        )
        .where(HerdTracking.id.in_(ids), ht_not_voided())
        .returning(HerdTracking.holder_contact)
        .tuples()
    )
    return [contact for (contact,) in voided if contact]


VOID_ACTION = "forsaljning_ogiltig"  # audit_log action: the sale holding the buyer was voided


def _drop_orphan_buyers(contact_ids, action, user):
    """
    A buyer lives as long as an active row holds it (ADR-0016): a sale undone, rejected or corrected away takes its
    buyer with it, a correction that rewrites the sale keeps it. Call at the end of the transaction.
    """
    if not contact_ids:
        return []
    return delete_buyer_contacts(_unheld(contact_ids), action, user)[1]


def _unheld(contact_ids):
    """The buyers among `contact_ids` that no active row holds."""
    held = HerdTracking.select(HerdTracking.holder_contact).where(
        HerdTracking.holder_contact.in_(list(contact_ids)), ht_not_voided()
    )
    return set(contact_ids) - {contact_id for (contact_id,) in held.tuples()}


def drop_kept_buyers(contact_ids, user, *, lock=False):
    """
    K1, FB6: the buyers kept across Dra tillbaka among `contact_ids` that no active row holds go now, when their sale
    is gone from the report. With `lock`, the queue's items and the rabbits are locked first, in the queue's order
    (erase_buyer_contact); without it the caller holds them.
    """
    if not contact_ids:
        return
    if lock:
        holding = list(HerdTracking.select().where(HerdTracking.holder_contact.in_(list(contact_ids))))
        lock_buyer_rows(holding, {row.individual_id for row in holding})
    _remove_after_commit(_drop_orphan_buyers(contact_ids, VOID_ACTION, user))


def _remove_after_commit(paths, files=None):
    """
    The queue originals a deletion let go of: removed now that the void's transaction has committed, or handed to
    `files` when the caller owns an outer transaction and removes them after its own commit (inbox_purge.
    remove_originals). Only an outer transaction that passes no list leaves them to remove_orphans; none does.
    """
    if files is not None:
        files.extend(paths)
    elif paths and not DB_PROXY.in_transaction():
        from utils.inbox_purge import remove_originals  # pylint: disable=import-outside-toplevel  # see below

        remove_originals(paths)


def buyer_items(rows, lock=False):
    """
    The queue's items whose documents may show the buyers of `rows`, the rows a caller is about to void: the items
    with documents of the rabbits or of their sales, when a row holds a buyer outside the association, else none.
    The buyers are read afresh, never from rows or a query a caller read earlier (attach_buyer may have set one
    since). With `lock`, they are locked in the queue's own order (it locks its item, then the rabbit): call
    before lock_individuals.
    """
    rows = list(rows)
    if (
        not HerdTracking.select()
        .where(HerdTracking.id.in_([r.id for r in rows]), HerdTracking.holder_contact.is_null(False))
        .exists()
    ):
        return set()
    individual_ids = {r.individual_id for r in rows}
    sales = HerdTracking.select(HerdTracking.id).where(HerdTracking.individual.in_(individual_ids))
    documents = InboxDocument.select(InboxDocument.item).where(
        InboxDocument.individual.in_(individual_ids) | InboxDocument.herd_tracking_id.in_(sales)
    )
    query = InboxItem.select(InboxItem.id).where(InboxItem.id.in_(documents)).order_by(InboxItem.id)
    return {item_id for (item_id,) in (query.for_update() if lock else query).tuples()}


def lock_buyer_items(individual_ids):
    """
    For a caller that holds its own transaction and voids the rabbits' active rows (unpromote): the items, locked
    before the caller's own lock on the rabbits. Returns them for void_all_for_unpromote to revalidate.
    """
    rows = HerdTracking.select().where(HerdTracking.individual.in_(list(individual_ids)), ht_not_voided())
    return buyer_items(rows, lock=True)


QUEUE_CHANGED = "Inkorgen ändrades under tiden. Försök igen."


class QueueChanged(HerdTrackingConflict):
    """An item was linked to the rabbits after lock_buyer_rows locked their items; nothing is written yet."""

    def __init__(self):
        super().__init__(QUEUE_CHANGED)


def lock_buyer_rows(rows, individual_ids):
    """
    The queue's order for a caller that voids `rows` or deletes their buyers: their items (buyer_items), then the
    rabbits, then the item set read again. An item linked to the rabbits or their sales after the first read would be
    locked after the rabbit, and its holder may wait for the rabbit: QueueChanged then, before anything is written,
    for the caller to roll back and answer 409. Returns the items.
    """
    items = buyer_items(rows, lock=True)
    lock_individuals(individual_ids)
    _require_same_items(rows, items)
    return items


def _require_same_items(rows, items):
    """
    Under the rabbit lock: the rows to void hold no buyer whose queue items were not locked before it (a proof
    linked, or attach_buyer, in between). Otherwise 409, never a lock taken out of order.
    """
    if not buyer_items(rows) <= items:
        raise QueueChanged


def void_all_for_unpromote(individual, user, operation_id=None, files=None, items=None):
    """
    Retire every active row of an un-promoted individual in one operation. A caller in its own transaction passes
    `files` and removes them after its commit, and `items`, what lock_buyer_items locked before its own lock on
    the rabbit; without them this locks the items itself. An item that has appeared since is a 409, never a lock
    taken out of order.
    """
    op = new_operation_id(operation_id)
    with DB_PROXY.atomic():
        if items is None:
            items = lock_buyer_items([individual.id])
        lock_individuals([individual.id])
        rows = list(HerdTracking.select().where(HerdTracking.individual == individual.id, ht_not_voided()))
        if not buyer_items(rows) <= items:
            raise HerdTrackingConflict(QUEUE_CHANGED)
        if not user.is_admin and _moves_across_genebanks(individual, rows, []):
            raise HerdTrackingForbidden(GENEBANK_CHANGE_ADMIN_ONLY)
        paths = _drop_orphan_buyers(_void_rows(rows, user, UNPROMOTE_REASON, op), VOID_ACTION, user)
    _remove_after_commit(paths, files)
    return rows


def legacy_ht_kind(holder_code, target_code):
    """Kind for legacy update_individual rows: a row in the current herd attests, any other herd moves."""
    return "ATTESTATION" if holder_code == target_code else "TRANSFER"


WRITER_KINDS = ("BIRTH", "TRANSFER", "ATTESTATION")  # CORRECTION only via correct_herd_tracking
DATE_BEFORE_LATEST = "Datumet är före kaninens senaste registrerade händelse."

Violation = namedtuple("Violation", "code row_id detail")


def resolve_herd(herd):
    if isinstance(herd, Herd):
        return herd
    found = Herd.get_or_none(Herd.id == herd) if isinstance(herd, int) else Herd.get_or_none(Herd.herd == herd)
    if found is None:
        raise HerdTrackingInvalid(f"Okänd besättning: {herd}.")
    return found


def _active_rows(individual_id):
    """The individual's active rows in chronological order (re-read under the lock)."""
    rows = HerdTracking.select().where(HerdTracking.individual == individual_id, ht_not_voided())
    return sorted(rows, key=ht_sort_key)


def _row_ref(row):
    return {
        "id": row.id,
        "date": coerce_date(row.herd_tracking_date).isoformat(),
        "kind": row.kind,
        "herd": row.herd.herd if row.herd_id else None,
    }


def check_invariants(individual, rows, buyer_keys=None):
    """I1–I4 over one individual's ACTIVE rows; returns a set of Violation. `buyer_keys`: a cache for _buyer_key."""
    ordered = sorted(rows, key=ht_sort_key)
    found = set()
    births = [r for r in ordered if r.kind == "BIRTH"]
    for extra in births[1:]:
        found.add(Violation("I1", extra.id, "Kaninen har mer än en aktiv födelserad."))
    birth_date = coerce_date(births[0].herd_tracking_date) if births else None
    holder, holder_contact = individual.origin_herd_id, None
    for row in ordered:
        day = coerce_date(row.herd_tracking_date)
        if birth_date and day < birth_date:
            found.add(Violation("I3", row.id, f"Händelsen {day} ligger före födelseraden {birth_date}."))
        if row.kind == "ATTESTATION" and row.herd_id != holder:
            found.add(Violation("I2", row.id, "En årsrapport måste gälla besättningen som har kaninen vid datumet."))
        if (
            row.kind in ("TRANSFER", "CORRECTION")
            and row.herd_id == holder
            and not _outside_resale(row, holder_contact, buyer_keys)
        ):
            found.add(Violation("I4", row.id, "En flytt måste gå till en annan besättning än den som har kaninen."))
        if row.kind in HOLDER_CHANGING_KINDS:
            holder, holder_contact = row.herd_id, row.holder_contact_id
    return found


def _buyer_key(contact_id, cache=None):
    """
    The buyer as a person (name and town, any case). `cache` (from _buyer_keys) holds the (name, town) as stored
    by id; it is filled and read when given.
    """
    if cache is not None and contact_id in cache:
        stored = cache[contact_id]
    else:
        contact = BuyerContact.get_or_none(BuyerContact.id == contact_id) if contact_id else None
        stored = (contact.name, contact.town) if contact else None
        if cache is not None:
            cache[contact_id] = stored
    return (stored[0].casefold(), stored[1].casefold()) if stored else None


def _buyer_keys(rows):
    """(name, town) of every buyer `rows` hold, in one query: the cache herd_tracking_history passes around."""
    ids = {r.holder_contact_id for r in rows if r.holder_contact_id}
    keys = dict.fromkeys(ids)
    if ids:
        query = BuyerContact.select(BuyerContact.id, BuyerContact.name, BuyerContact.town)
        for contact_id, name, town in query.where(BuyerContact.id.in_(list(ids))).tuples():
            keys[contact_id] = (name, town)
    keys[None] = None
    return keys


def _outside_resale(row, previous_contact, buyer_keys=None):
    """
    ADR-0016's one exception to I4: a TRANSFER (or a CORRECTION that carries one's buyer) within GX1/MX1 holding a
    new buyer, another person (name and town) than the one before it. A buyer erased later turns the row into a
    violation the delta check tolerates.
    """
    return (
        row.kind in ("TRANSFER", "CORRECTION")
        and row.herd_id is not None
        and row.herd.herd in OUTSIDE_GENEBANK_HERDS
        and row.holder_contact_id is not None
        and row.holder_contact_id != previous_contact
        and _buyer_key(row.holder_contact_id, buyer_keys) != _buyer_key(previous_contact, buyer_keys)
    )


def _assert_no_new_violations(individual, before, after):
    """Delta check: the operation may not INTRODUCE a violation; legacy ones (preflight P1–P5) are tolerated."""
    known = {(v.code, v.row_id) for v in check_invariants(individual, before)}
    introduced = sorted(
        (v for v in check_invariants(individual, after) if (v.code, v.row_id) not in known),
        key=lambda v: (v.code, v.row_id or 0),
    )
    if any(r.kind == "BIRTH" for r in before) and not any(r.kind == "BIRTH" for r in after):
        introduced.append(Violation("I5", None, "En födelserad kan bara ersättas, inte tas bort."))
    if introduced:
        raise HerdTrackingConflict(
            f"Ändringen skulle göra besättningshistoriken motsägelsefull: {introduced[0].detail}",
            rows=[{"id": v.row_id, "code": v.code, "detail": v.detail} for v in introduced],
        )


def _violated_constraint(exc):
    """Name of the constraint/index a PostgreSQL IntegrityError tripped (peewee keeps the driver error in .orig)."""
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def _touched_by(operation_id):
    """Rows an operation wrote, voided or (an undo) restored."""
    return (
        (HerdTracking.operation_id == operation_id)
        | (HerdTracking.voided_operation_id == operation_id)
        | (HerdTracking.restored_operation_id == operation_id)
    )


def _operation_rows(individual_ids, operation_id):
    """Rows this operation already touched for these individuals (idempotency, scoped per individual)."""
    return list(
        HerdTracking.select().where(HerdTracking.individual.in_(list(individual_ids)), _touched_by(operation_id))
    )


KEPT_BUYER_GONE = "Köparen finns inte längre sparad. Skriv köparens namn och ort."


def record_herd_tracking(
    individual,
    herd,
    date,
    kind,
    user,
    operation_id=None,
    *,
    notes=None,
    yearly_herd_report=None,
    transfer_id=None,
    buyer=None,
    holder_contact=None,
    address_optional=False,
    buyer_removed=False,
):
    """
    The central writer. Locks the individual, re-reads its
    active rows, requires date >= the latest active row (except BIRTH), sets
    from_herd to the holder at the date, checks I1–I4 as a delta and writes.
    Idempotent per (individual, operation_id). `buyer` (a sale to GX1/MX1 only) is the buyer outside the
    association as buyer_contact_fields reads it, stored with the row in the same transaction. `holder_contact` (a
    BuyerContact id) links a buyer kept across Dra tillbaka instead (K1): one no active row holds, whose purge_at goes
    back to five years from the sale; only utils.arsrapport passes it, once it has checked where the buyer came from.
    """
    if kind not in WRITER_KINDS:
        raise HerdTrackingInvalid(f"Okänd händelsetyp: {kind!r}.")
    op = new_operation_id(operation_id)
    target = resolve_herd(herd)
    try:
        when = coerce_date(date)
    except (TypeError, ValueError) as exc:
        raise HerdTrackingInvalid("Ogiltigt datum.") from exc
    reject_contact_details(notes)
    if buyer_removed and (buyer is not None or holder_contact is not None):
        raise HerdTrackingConflict(BUYER_REMOVED)
    if (buyer is not None or holder_contact is not None or buyer_removed) and (
        kind != "TRANSFER" or target.herd not in OUTSIDE_GENEBANK_HERDS
    ):
        raise HerdTrackingInvalid("Köparens namn och ort registreras bara vid försäljning utanför genbanken.")
    contact_fields = None
    if buyer is not None:
        # A new sale needs the address, except from a manager or admin (old paper certificates); corrections never.
        address_required = not address_optional and not is_manager_of(user, target.genebank_id)
        contact_fields = buyer_contact_fields(buyer, when, address_required=address_required)
    individual_id = individual.id if isinstance(individual, Individual) else int(individual)
    code_id = getattr(user, "access_code_id", None)  # the report link as the signer: no account, no signature
    signer = {"access_code_id": code_id} if code_id is not None else {"signature": user}
    with DB_PROXY.atomic():
        lock_individuals([individual_id])
        ind = Individual.get_by_id(individual_id)
        done = _operation_rows([individual_id], op)
        if done:
            return next((r for r in done if r.operation_id == op), done[0])
        _reject_buyer_name([notes], [individual_id], [contact_fields["name"]] if contact_fields else ())
        before = _active_rows(individual_id)
        existing_birth = next((r for r in before if r.kind == "BIRTH"), None)
        if kind == "BIRTH" and existing_birth is not None:
            detail = "Kaninen har redan en aktiv födelserad."
            raise HerdTrackingConflict(detail, rows=[{"id": existing_birth.id, "code": "I1", "detail": detail}])
        if kind != "BIRTH" and before and when < coerce_date(before[-1].herd_tracking_date):
            raise HerdTrackingConflict(DATE_BEFORE_LATEST, rows=[_row_ref(before[-1])])
        holder_id = before[-1].herd_id if before else ind.origin_herd_id
        if (
            kind == "TRANSFER"
            and target.id == holder_id
            and target.herd in OUTSIDE_GENEBANK_HERDS
            and (contact_fields is None or not is_manager_of(user, target.genebank_id))
        ):
            raise HerdTrackingConflict(
                f"Kaninen finns redan i {target.herd}. En ny köpare utanför föreningen registreras av "
                "genbanksansvarig, med köparens namn och ort."
            )
        contact = _new_buyer(contact_fields, user, when) if contact_fields else None
        if holder_contact is not None:  # locked against the nightly purge, which deletes by id
            contact = BuyerContact.select().where(BuyerContact.id == holder_contact).for_update().first()
            held = HerdTracking.select().where(HerdTracking.holder_contact == holder_contact, ht_not_voided())
            if contact is None or held.exists():
                raise HerdTrackingInvalid(KEPT_BUYER_GONE)
            _set_buyer_sale_date(contact.id, when)
        try:
            with DB_PROXY.atomic():
                row = HerdTracking.create(
                    individual=individual_id,
                    herd=target,
                    from_herd=None if kind == "BIRTH" else holder_id,
                    **signer,
                    herd_tracking_date=when,
                    kind=kind,
                    operation_id=op,
                    notes=notes,
                    yearly_herd_report=yearly_herd_report,
                    transfer_id=transfer_id,
                    holder_contact=contact,
                    buyer_removed=buyer_removed or (bool(contact_fields) and contact is None),
                )
        except IntegrityError as exc:
            if _violated_constraint(exc) != "idx_herdtracking_report_attestation":
                raise
            raise HerdTrackingConflict("Kaninen har redan en aktiv rad för den här rapporten.") from exc
        if contact_fields and contact is not None:
            queue_buyer_mails(contact, row)
        _assert_no_new_violations(ind, before, before + [row])
    return row


BIRTH_HERD_CHANGED_REASON = "Ersatt: ändrad ursprungsbesättning"
BIRTH_DATE_CHANGED_REASON = "Ersatt: ändrat födelsedatum"


def replace_birth_row(individual, user, *, herd=None, date=None, reason, operation_id=None):
    """
    Replace-not-remove: void the active BIRTH and write its
    replacement with a new herd and/or date in one operation. ht_order_desc() keeps
    the replacement first within its day even though its id is higher.
    """
    op = new_operation_id(operation_id)
    with DB_PROXY.atomic():
        lock_individuals([individual.id])
        ind = Individual.get_by_id(individual.id)
        if _operation_rows([ind.id], op):
            replayed = HerdTracking.get_or_none(
                (HerdTracking.individual == ind.id) & (HerdTracking.operation_id == op) & (HerdTracking.kind == "BIRTH")
            )
            if replayed is not None:
                return replayed
            raise HerdTrackingConflict("Operationen har redan använts för en annan åtgärd.")
        before = _active_rows(ind.id)
        birth = next((r for r in before if r.kind == "BIRTH"), None)
        if birth is None:
            raise HerdTrackingNotFound("Individual does not have birth_date herdtracking event")
        new_herd = resolve_herd(herd) if herd is not None else None
        new_date = coerce_date(date) if date is not None else None
        if (new_herd is None or new_herd.id == birth.herd_id) and (
            new_date is None or new_date == coerce_date(birth.herd_tracking_date)
        ):
            return birth  # nothing to replace: no void, no new row
        _void_rows([birth], user, reason, op)  # a BIRTH row never holds a buyer
        new_birth = HerdTracking.create(
            individual=ind.id,
            herd=new_herd if new_herd is not None else birth.herd_id,
            from_herd=None,
            signature=user,
            herd_tracking_date=new_date if new_date is not None else birth.herd_tracking_date,
            kind="BIRTH",
            operation_id=op,
        )
        after = [r for r in before if r.id != birth.id] + [new_birth]
        # A new birth date can reorder a tolerated legacy history so that another genebank holds the rabbit.
        if not user.is_admin and _moves_across_genebanks(ind, before, after):
            raise HerdTrackingForbidden(GENEBANK_CHANGE_ADMIN_ONLY)
        _assert_no_new_violations(ind, before, after)
    return new_birth


SALE_UNDO_WINDOW = timedelta(days=7)
ATTESTATION_UNDO_WINDOW = timedelta(days=7)
CONTACT_MANAGER = "Kontakta genbanksansvarig."
BUYER_PRIVACY_HELP = "Skriv inte köparens namn eller kontaktuppgifter."
OWN_ROWS_ONLY = f"Bara den som registrerade raden kan ångra den. {CONTACT_MANAGER}"  # ADR-0017; managers are exempt

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
# A Swedish number starts with +46/46 or a trunk 0 glued to a non-zero area-code digit ("070", "(08)") and
# never continues a word or a date ("2025-09-30", "G1274-2112"). "0 2025…" and "0012 …" never start one.
_PHONE = re.compile(r"(?:\+|(?<![\w-]))\(?(?:46[\s.()/-]*(?:\(0\)\s*)?|0)[1-9][\d\s./()-]*\d")
# 9+ digits: every real number (08-123 45 67) has them; a DD MM YYYY date ("01 10 2025") has 8.
_PHONE_MIN_DIGITS = 9
# A link: a scheme, "www." or a host such as "example.se" (a lower-case top domain, so "St.Olof" is none).
_URL = re.compile(r"(?i:[a-z][a-z0-9+.-]*://|www\.)|\b[\w-]+\.[a-z]{2,}\b")
# In an address only a scheme or "www." is a link: "2.th", "lgh.nr" and "St.gatan" are ordinary address text.
_LINK = re.compile(r"(?i:[a-z][a-z0-9+.-]*://|www\.)")


def reject_contact_details(text, *, links=False):
    """No buyer identity in free text: it lives forever in audit_log."""
    if not text:
        return
    if (
        (links and _URL.search(text))
        or _EMAIL.search(text)
        or any(len(re.sub(r"\D", "", m.group(0))) >= _PHONE_MIN_DIGITS for m in _PHONE.finditer(text))
    ):
        raise HerdTrackingInvalid(BUYER_PRIVACY_HELP)


def require_reason(reason):
    if reason is not None and not isinstance(reason, str):
        raise HerdTrackingInvalid("Anledningen måste vara text.")
    cleaned = (reason or "").strip()
    if not cleaned:
        raise HerdTrackingInvalid("Ange en anledning.")
    reject_contact_details(cleaned)
    return cleaned


def is_manager_of(user, genebank_id):
    return bool(user.is_admin or (user.is_manager and genebank_id in user.is_manager))


def _row_genebank_id(row, individual):
    """Manager rights follow the ROW's herd genebank, not the individual's current herd."""
    return row.herd.genebank_id if row.herd_id else individual.origin_herd.genebank_id


def _has_dependent_breeding(individual_id, row):
    """Undo-sale rule 5 (incl. a doe bought pregnant, mating dated before the sale)."""
    row_date = coerce_date(row.herd_tracking_date)
    return (
        Breeding.select()
        .where(
            (Breeding.mother == individual_id) | (Breeding.father == individual_id),
            (Breeding.breeding_herd_id == row.herd_id)
            | (fn.COALESCE(Breeding.birth_date, Breeding.breed_date) >= row_date),
        )
        .exists()
    )


def sale_undo_denial(user, row, active_rows, transfer_herd_ids=None):
    """None if the SELLER may undo this sale, else a Swedish reason. Cheap checks first."""
    if row.kind != "TRANSFER" or row.voided_at is not None:
        return "Bara en aktiv försäljning kan ångras."
    if row.transfer_id is not None:
        return f"Överlåtelsen avbryts i överlåtelseflödet. {CONTACT_MANAGER}"
    if (
        row.from_herd_id is None
        or row.from_herd.herd in OUTSIDE_GENEBANK_HERDS  # GX1/MX1 owners are never sellers
        or row.from_herd_id not in (user.transfer_herd_ids() if transfer_herd_ids is None else transfer_herd_ids)
    ):
        return f"Bara säljaren kan ångra försäljningen. {CONTACT_MANAGER}"
    if not active_rows or active_rows[-1].id != row.id:
        return f"Något har registrerats på kaninen efter försäljningen. {CONTACT_MANAGER}"
    if _now_utc() - row.created_at > SALE_UNDO_WINDOW:
        return f"Försäljningen registrerades för mer än 7 dagar sedan. {CONTACT_MANAGER}"
    if _has_dependent_breeding(row.individual_id, row):
        return f"Kaninen har en parning eller kull registrerad efter försäljningen. {CONTACT_MANAGER}"
    if row.signature_id != user.id:  # last, so every earlier refusal keeps its message; unsigned rows too
        return OWN_ROWS_ONLY
    return None


GENEBANK_CHANGE_ADMIN_ONLY = "Bara administratör kan ändra eller ångra ett genbanksbyte."


def _holder_genebank(individual, rows):
    """Genebank of the holder `rows` project: the latest row's herd (current_holder_row), else the origin."""
    latest = max(rows, key=ht_sort_key, default=None)
    return (latest.herd if latest is not None and latest.herd_id else individual.origin_herd).genebank_id


def _changes_genebank(row, individual, rows):
    """A TRANSFER/CORRECTION between genebanks: only an admin correction makes or reverses one. A legacy row
    without from_herd moves from the holder before it in `rows`."""
    if row.kind not in ("TRANSFER", "CORRECTION") or row.herd_id is None:
        return False
    if row.from_herd_id is not None:
        source = row.from_herd.genebank_id
    else:
        source = _holder_genebank(individual, [r for r in rows if ht_sort_key(r) < ht_sort_key(row)])
    return source != row.herd.genebank_id


def _moves_across_genebanks(individual, before, after):
    """A row the change adds or removes crosses genebanks, or the holder ends up in another genebank (a
    void can expose an older holder)."""
    before_ids, after_ids = {r.id for r in before}, {r.id for r in after}
    return (
        any(_changes_genebank(r, individual, before) for r in before if r.id not in after_ids)
        or any(_changes_genebank(r, individual, after) for r in after if r.id not in before_ids)
        or _holder_genebank(individual, before) != _holder_genebank(individual, after)
    )


def sale_months(individual):
    """
    "YYYY-MM" of each change of holder for the public certificate check page (stamboken #6), read from the
    corrected history (Jonas 2026-11-23): an active TRANSFER or CORRECTION to another herd in the same genebank as
    the holder before it, or ADR-0016's resale to a new buyer within GX1/MX1. The holder is walked over the active
    rows: a stored from_herd can name a row voided since. A move between genebanks (an admin's register fix), a row
    without a receiving herd and a migrated row repeating the holder are no change of holder.
    """
    months, holder = [], individual.origin_herd
    for r in _active_rows(individual.id):
        if r.herd_id is None or r.kind not in HOLDER_CHANGING_KINDS:
            continue
        # ADR-0016's resale: a row within the GX1/MX1 holder that holds a buyer, or held one erased since.
        resale = (
            holder is not None
            and r.herd_id == holder.id
            and r.herd.herd in OUTSIDE_GENEBANK_HERDS
            and (r.holder_contact_id is not None or r.buyer_removed)
        )
        if (
            r.kind in ("TRANSFER", "CORRECTION")
            and holder is not None
            and (r.herd_id != holder.id or resale)
            and r.herd.genebank_id == holder.genebank_id
        ):
            months.append(coerce_date(r.herd_tracking_date).strftime("%Y-%m"))
        holder = r.herd
    return months


REPORT_ROW = "Raden kommer från årsrapporten. Ändra årsrapporten i stället."
REPORT_LATER_ROW = "Något har registrerats på kaninen efter årsrapporten. Genbanksansvarig kan rätta."
BIRTH_NOT_VOIDABLE = "En födelserad kan inte ångras — den kan bara ersättas."


def report_owners(op_ids):
    """
    {str(op): the submitted yearly report whose submissions wrote op}, in one query; ops no submitted report
    wrote are left out. The report comes with its herd and round, so `{herd, year}` costs nothing more.
    """
    wanted = {str(op) for op in op_ids if op is not None}
    if not wanted:
        return {}
    submissions = (
        YearlyReportSubmission.select(YearlyReportSubmission.operation_ids, YearlyHerdReport, Herd, YearlyReportRound)
        .join(YearlyHerdReport)
        .join(Herd)
        .switch(YearlyHerdReport)
        .join(YearlyReportRound)
        .where(YearlyHerdReport.status == "submitted", YearlyReportSubmission.operation_ids.contains_any(*wanted))
    )
    return {op: s.report for s in submissions for op in s.operation_ids if op in wanted}


def latest_death_op(individual_id):
    """The operation id of the rabbit's latest RecordDeath that no Undo names (ADR-0017), or None."""
    undone = IndividualCommand.select(IndividualCommand.undoes).where(
        IndividualCommand.individual == individual_id, IndividualCommand.undoes.is_null(False)
    )
    return (
        IndividualCommand.select(IndividualCommand.operation_id)
        .where(
            IndividualCommand.individual == individual_id,
            IndividualCommand.command == "RecordDeath",
            IndividualCommand.operation_id.not_in(undone),
        )
        .order_by(IndividualCommand.created_at.desc(), IndividualCommand.id.desc())
        .scalar()
    )


def void_denial(user, row, active_rows, individual, transfer_herd_ids=None, owners=None):
    """The void permission table. None = allowed. `owners`: report_owners for the row's op, looked up if not given."""
    if row.kind == "BIRTH":
        return BIRTH_NOT_VOIDABLE
    if not user.is_admin and _moves_across_genebanks(individual, active_rows, [r for r in active_rows if r != row]):
        return GENEBANK_CHANGE_ADMIN_ONLY
    if is_manager_of(user, _row_genebank_id(row, individual)):
        return None
    if str(row.operation_id) in (report_owners([row.operation_id]) if owners is None else owners):
        return REPORT_ROW  # spec 8: the rabbit page leads to Ändra, so the report and the register agree
    if row.kind == "ATTESTATION":
        if row.herd.herd in OUTSIDE_GENEBANK_HERDS:  # owner privileges on GX1/MX1 never authorise
            return f"Kaninen är såld utanför genbanken. {CONTACT_MANAGER}"
        if not active_rows or active_rows[-1].id != row.id:
            return f"Bara den senaste händelsen kan ångras. {CONTACT_MANAGER}"
        if _now_utc() - row.created_at > ATTESTATION_UNDO_WINDOW:
            return f"Årsrapporten registrerades för mer än 7 dagar sedan. {CONTACT_MANAGER}"
        if row.herd_id not in user.effective_herd_ids():
            return f"Du kan bara ångra årsrapporter för din egen besättning. {CONTACT_MANAGER}"
        if row.signature_id != user.id:
            return OWN_ROWS_ONLY
        return None
    if row.kind == "TRANSFER":
        return sale_undo_denial(user, row, active_rows, transfer_herd_ids)
    return f"Bara genbanksansvarig kan ångra en korrigering. {CONTACT_MANAGER}"


def _behind_report_sales(row, active_rows, report_ops):
    """
    K3, fråga 15 b: the report's attestation goes from behind the sales that stay, so the rabbit counts on 31/12 via
    the move. Every later row is a TRANSFER that an approved proposal of the same report wrote, or the report's own
    (FB5: a sale the owner registered, which a link's or a caretaker's Dra tillbaka keeps).
    """
    later = [r for r in active_rows if ht_sort_key(r) > ht_sort_key(row)]
    if row.kind != "ATTESTATION" or row.yearly_herd_report_id is None or not later:
        return False
    approved = SaleProposal.select(SaleProposal.herd_tracking_id).where(
        SaleProposal.report == row.yearly_herd_report_id, SaleProposal.state == "godkand"
    )
    approved = {proposal.herd_tracking_id for proposal in approved}
    return all(r.kind == "TRANSFER" and (r.id in approved or str(r.operation_id) in report_ops) for r in later)


def report_void_denial(user, row, active_rows, individual, report_ops):
    """
    The yearly report's right (ADR-0017, addendum 2026-11-14): the report's own rows, whoever wrote them and however
    old, unless something was registered after them other than the report's sales (_behind_report_sales). The right
    itself is checked at report level. None = allowed.
    """
    if str(row.operation_id) not in report_ops:
        return "Raden hör inte till årsrapporten."
    if row.kind == "BIRTH":
        return BIRTH_NOT_VOIDABLE
    if not user.is_admin and _moves_across_genebanks(individual, active_rows, [r for r in active_rows if r != row]):
        return GENEBANK_CHANGE_ADMIN_ONLY
    if not active_rows or (active_rows[-1].id != row.id and not _behind_report_sales(row, active_rows, report_ops)):
        return REPORT_LATER_ROW
    if row.kind == "TRANSFER":  # the seller's rules that do not depend on who or when (sale_undo_denial)
        if row.transfer_id is not None:
            return f"Överlåtelsen avbryts i överlåtelseflödet. {CONTACT_MANAGER}"
        if _has_dependent_breeding(row.individual_id, row):
            return "Kaninen har en parning eller kull registrerad efter försäljningen. Genbanksansvarig kan rätta."
    return None


def void_herd_tracking(ht_id, user, reason, operation_id=None, typed=True, *, report_ops=None, keep_buyer_until=None):
    """
    Void one row (also "Ångra försäljning"). Idempotent per (individual, operation_id):
    a replayed operation returns the row it voided; an already voided row is a no-op.
    Checks I1–I5 afterwards. Callers must gate READ access first: the idempotent
    replay returns before the permission check. `typed`: the reason is a user's text (checked against the buyer's
    name), not a system reason; from one who may not see the buyers (can_see_buyer) it is UNDO_REASON instead when a
    row of the rabbit, live or voided, holds a buyer, as Access.reads_buyers strips the report's. With `report_ops`
    (a frozenset of str operation ids), the yearly report's right replaces the void table: only utils.arsrapport
    passes them, once it has checked it.
    With `keep_buyer_until` (a timestamp, Dra tillbaka's K1 and K2) a buyer no active row holds any more stays,
    held by the voided row only, with that purge_at.
    """
    cleaned = require_reason(reason)
    op = new_operation_id(operation_id)
    row = HerdTracking.get_or_none(HerdTracking.id == ht_id)
    if row is None:
        raise HerdTrackingNotFound("Raden finns inte.")
    with DB_PROXY.atomic():
        items = buyer_items([row], lock=True)
        lock_individuals([row.individual_id])
        done = _operation_rows([row.individual_id], op)
        if done:
            return next((r for r in done if r.voided_operation_id == op), done[0])
        row = HerdTracking.get_by_id(ht_id)
        _require_same_items([row], items)
        if row.voided_at is not None:
            return row
        individual = Individual.get_by_id(row.individual_id)
        before = _active_rows(individual.id)
        if report_ops is None:
            denial = void_denial(user, row, before, individual)
        else:
            denial = report_void_denial(user, row, before, individual, report_ops)
        if denial:
            raise HerdTrackingForbidden(denial)
        if typed and not can_see_buyer(user, _row_genebank_id(row, individual)) and _holds_buyer(individual.id):
            # A seller's own row (void_denial): its text is never checked against the buyers, so it answers no guess
            cleaned, typed = UNDO_REASON, False
        if typed:
            _reject_buyer_name([cleaned], [individual.id])
        voided = _void_rows([row], user, cleaned, op)
        _assert_no_new_violations(individual, before, [r for r in before if r.id != row.id])
        if keep_buyer_until is None:
            paths = _drop_orphan_buyers(voided, VOID_ACTION, user)
        else:
            paths, kept = [], list(_unheld(voided))
            BuyerContact.update(purge_at=keep_buyer_until).where(BuyerContact.id.in_(kept)).execute()
    _remove_after_commit(paths)
    return HerdTracking.get_by_id(ht_id)


CORRECTION_EVENT_KINDS = ("TRANSFER", "CORRECTION", "BIRTH", "ATTESTATION")


def _stockholm_today():
    return datetime.now(ZoneInfo("Europe/Stockholm")).date()


def _birth_matches_individual(individual, herd_id, when):
    """The Individual/BIRTH coupling: a BIRTH sits in origin_herd on the breeding's birth date."""
    birth_date = individual.breeding.birth_date if individual.breeding_id else None
    return herd_id == individual.origin_herd_id and (not birth_date or coerce_date(when) == coerce_date(birth_date))


def _decouples_birth(individual, after):
    """True if an active BIRTH in `after` no longer matches the individual (the undo path)."""
    return any(
        not _birth_matches_individual(individual, r.herd_id, r.herd_tracking_date) for r in after if r.kind == "BIRTH"
    )


def _parse_events(events, individual):
    parsed, previous = [], None
    genebank_id = individual.origin_herd.genebank_id
    for number, event in enumerate(events or [], 1):
        kind = event.get("kind")
        if kind not in CORRECTION_EVENT_KINDS:
            raise HerdTrackingInvalid(f"Händelse {number}: okänd typ.")
        try:
            when = coerce_date(event.get("date"))
        except (TypeError, ValueError) as exc:
            raise HerdTrackingInvalid(f"Händelse {number}: ogiltigt datum (ÅÅÅÅ-MM-DD).") from exc
        if when > _stockholm_today():
            raise HerdTrackingInvalid(f"Händelse {number}: datumet ligger i framtiden.")
        if previous and when < previous:
            raise HerdTrackingInvalid("Händelserna måste anges i kronologisk ordning.")
        raw_herd = event.get("herd")
        if not isinstance(raw_herd, str):
            raise HerdTrackingInvalid(f"Händelse {number}: ange besättningen som text (t.ex. G1).")
        herd = Herd.get_or_none(Herd.herd == raw_herd)
        if herd is None or herd.genebank_id != genebank_id:
            raise HerdTrackingInvalid(f"Händelse {number}: okänd besättning i kaninens genbank.")
        if kind == "BIRTH" and not _birth_matches_individual(individual, herd.id, when):
            raise HerdTrackingInvalid(
                f"Händelse {number}: en födelserad måste gälla kaninens ursprungsbesättning och födelsedatum. "
                "Ändra ursprungsbesättning eller födelsedatum på kaninen i stället."
            )
        raw_notes = event.get("notes")
        if raw_notes is not None and not isinstance(raw_notes, str):
            raise HerdTrackingInvalid(f"Händelse {number}: anteckningen måste vara text.")
        notes = (raw_notes or "").strip() or None
        reject_contact_details(notes)
        # A new buyer outside the association (the queue's late sale); a rewritten sale's buyer is carried over.
        buyer = event.get("buyer")
        if buyer is not None and (kind != "TRANSFER" or herd.herd not in OUTSIDE_GENEBANK_HERDS):
            raise HerdTrackingInvalid(f"Händelse {number}: en köpare hör bara till en försäljning utanför genbanken.")
        parsed.append(
            {
                "date": when,
                "herd": herd,
                "kind": kind,
                "notes": notes,
                "buyer": buyer_contact_fields(buyer, when) if buyer is not None else None,
            }
        )
        previous = when
    return parsed


def _holder_before(individual, rows, when, kind):
    """Holder just before an event inserted at (when, kind) — any row kind counts."""
    key = (when, 0 if kind == "BIRTH" else 1, float("inf"))
    prior = [r for r in sorted(rows, key=ht_sort_key) if ht_sort_key(r) < key]
    return prior[-1].herd_id if prior else individual.origin_herd_id


BUYER_GONE = "Köparen raderades under tiden. Försök igen."
ONE_SALE_OUT = "Dela upp rättelsen: högst en försäljning ut till samma besättning per rättelse."
BUYERLESS_BEFORE_SALE = (
    "En försäljning utanför genbanken utan köpare kan inte läggas före en försäljning till samma besättning."
)
MOVES = ("TRANSFER", "CORRECTION")


def _outside_pairs(voided, parsed):
    """
    A correction touches at most one sale into each of GX1/MX1 (409 otherwise): one voided move and one new event,
    which then replaces it and takes its buyer (ADR-0016). Event index -> the voided row it replaces.
    """

    def outside(herd):  # a legacy move may have no herd
        return herd is not None and herd.herd in OUTSIDE_GENEBANK_HERDS

    herds = {r.herd_id for r in voided if r.kind in MOVES and outside(r.herd)}
    herds |= {e["herd"].id for e in parsed if e["kind"] in MOVES and outside(e["herd"])}
    pairs = {}
    for herd_id in herds:
        old = [r for r in voided if r.kind in MOVES and r.herd_id == herd_id]
        new = [i for i, e in enumerate(parsed) if e["kind"] in MOVES and e["herd"].id == herd_id]
        if len(old) > 1 or len(new) > 1:
            raise HerdTrackingConflict(ONE_SALE_OUT)
        if old and new:
            pairs[new[0]] = old[0]
    return pairs


def _refuse_buyerless_before_sale(rows, written):
    """
    A buyerless move into GX1/MX1 just before a row in the same herd would make that row's buyer a resale between
    two buyers outside the association (ADR-0016): refused.
    """
    ordered = sorted(rows, key=ht_sort_key)
    for row in written:
        # A removed buyer was a real one: the row after it is a resale between two buyers, as before.
        if row.holder_contact_id is not None or row.buyer_removed or row.kind not in ("TRANSFER", "CORRECTION"):
            continue
        if row.herd.herd not in OUTSIDE_GENEBANK_HERDS:
            continue
        later = ordered[ordered.index(row) + 1 :]
        if later and later[0].herd_id == row.herd_id:
            raise HerdTrackingConflict(BUYERLESS_BEFORE_SALE, rows=[_row_ref(later[0])])


def _refuse_buyerless_sales_outside(parsed, pairs):
    """
    A TRANSFER or CORRECTION into GX1/MX1 that a correction writes needs a buyer, unless it replaces a voided sale
    into the same herd (_outside_pairs), whose buyer, or lack of one, it takes over.
    """
    for index, event in enumerate(parsed):
        if event["kind"] not in MOVES or event["herd"].herd not in OUTSIDE_GENEBANK_HERDS:
            continue
        if event["buyer"] is not None and index in pairs and pairs[index].buyer_removed:
            raise HerdTrackingConflict(BUYER_REMOVED)  # never registered again, as in attach_buyer
        if event["buyer"] is None and index not in pairs:
            hint = "ange köparens namn och ort" if event["kind"] == "TRANSFER" else "välj Flytt, där köparen anges"
            raise HerdTrackingInvalid(f"Händelse {index + 1}: en försäljning utanför föreningen: {hint}.")


def correct_herd_tracking(individual, user, operation_id, void_ids, events, reason=None):
    """
    Privileged correction: void `void_ids` and write `events` in the given
    order WITHOUT the "date >= latest" rule; refuses a date that has other active
    non-BIRTH rows not voided here; checks I1–I5 as a delta. `reason` (the void
    reason) is required when `void_ids` is non-empty. Idempotent per (individual,
    operation_id): a replay returns the rows the first call wrote.
    """
    ind_id = individual.id if isinstance(individual, Individual) else int(individual)
    ind = Individual.get_by_id(ind_id)
    if not is_manager_of(user, ind.origin_herd.genebank_id):
        raise HerdTrackingForbidden("Bara genbanksansvarig eller administratör kan korrigera besättningshistoriken.")
    parsed = _parse_events(events, ind)
    void_ids = sorted({int(v) for v in (void_ids or [])})
    if not parsed and not void_ids:
        raise HerdTrackingInvalid("Ange minst en händelse eller en rad att ångra.")
    cleaned = require_reason(reason) if void_ids else None
    op = new_operation_id(operation_id)
    with DB_PROXY.atomic():
        lock_buyer_rows(HerdTracking.select().where(HerdTracking.id.in_(void_ids)), [ind_id])
        ind = Individual.get_by_id(ind_id)
        if _operation_rows([ind_id], op):
            return list(
                HerdTracking.select()
                .where(HerdTracking.individual == ind_id, HerdTracking.operation_id == op)
                .order_by(HerdTracking.id)
            )
        before = _active_rows(ind_id)
        by_id = {r.id: r for r in before}
        missing = [v for v in void_ids if v not in by_id]
        if missing:
            raise HerdTrackingConflict("Raderna finns inte eller är redan ångrade.", rows=[{"id": v} for v in missing])
        kept = [r for r in before if r.id not in void_ids]
        _reject_buyer_name(
            [cleaned, *(e["notes"] for e in parsed)], [ind_id], [e["buyer"]["name"] for e in parsed if e["buyer"]]
        )
        for event in parsed:
            same_day = [r for r in kept if r.kind != "BIRTH" and coerce_date(r.herd_tracking_date) == event["date"]]
            if same_day:
                raise HerdTrackingConflict(
                    "Det finns redan händelser samma dag. "
                    "Ångra dem i samma korrigering och mata in hela dagen i rätt ordning.",
                    rows=[_row_ref(r) for r in same_day],
                )
        births = [r for r in kept if r.kind == "BIRTH"] + [e for e in parsed if e["kind"] == "BIRTH"]
        if len(births) > 1:
            raise HerdTrackingConflict(
                "Kaninen kan bara ha en aktiv födelserad.",
                rows=[
                    {"id": r.id, "code": "I1", "detail": "Ångra den gamla födelseraden i samma korrigering."}
                    for r in kept
                    if r.kind == "BIRTH"
                ],
            )
        pairs = _outside_pairs([by_id[v] for v in void_ids], parsed)
        _refuse_buyerless_sales_outside(parsed, pairs)
        carried = {
            i: r.holder_contact_id for i, r in pairs.items() if parsed[i]["buyer"] is None and r.holder_contact_id
        }
        voided = _void_rows([by_id[v] for v in void_ids], user, cleaned, op)
        written, current = [], list(kept)
        for index, event in enumerate(parsed):
            birth = event["kind"] == "BIRTH"
            from_herd = None if birth else _holder_before(ind, current, event["date"], event["kind"])
            contact = _new_buyer(event["buyer"], user, event["date"]) if event["buyer"] else carried.get(index)
            try:
                with DB_PROXY.atomic():
                    row = HerdTracking.create(
                        individual=ind_id,
                        herd=event["herd"],
                        from_herd=from_herd,
                        signature=user,
                        herd_tracking_date=event["date"],
                        kind=event["kind"],
                        operation_id=op,
                        notes=event["notes"],
                        holder_contact=contact,
                        buyer_removed=(index in pairs and pairs[index].buyer_removed)
                        or (event["buyer"] is not None and contact is None),
                    )
            except IntegrityError as exc:  # the carried buyer went (a purge or an erasure) after it was read
                if _violated_constraint(exc) != "herd_tracking_holder_contact_id_fkey":
                    raise
                raise HerdTrackingConflict(BUYER_GONE) from exc
            if event["buyer"]:
                queue_buyer_mails(row.holder_contact, row)
            if index in carried:  # a corrected sale's buyer: five years from the sale's corrected date
                _set_buyer_sale_date(carried[index], event["date"])
            written.append(row)
            current.append(row)
        # Admin only (rolled back). An event's herd is in the origin genebank, but the holder before it may
        # not be: its reason is the row's note.
        if not user.is_admin and _moves_across_genebanks(ind, before, current):
            raise HerdTrackingForbidden(GENEBANK_CHANGE_ADMIN_ONLY)
        if any(_changes_genebank(r, ind, current) and not r.notes for r in written):
            raise HerdTrackingInvalid("Ange en anledning i anteckningen för ett genbanksbyte.")
        _refuse_buyerless_before_sale(current, written)
        _assert_no_new_violations(ind, before, current)
        paths = _drop_orphan_buyers(voided, VOID_ACTION, user)
    _remove_after_commit(paths)
    return written


def _unvoid_rows(rows, operation_id):
    """
    WHITELISTED in-place UPDATE #2 (undo_herd_tracking_operation only): clear the void
    fields and record the undo that restored the row, so undoing that undo re-voids it.
    """
    ids = [r.id for r in rows]
    if not ids:
        return 0
    return (
        HerdTracking.update(
            voided_at=None,
            voided_by_user=None,
            voided_by_access_code_id=None,
            voided_reason=None,
            voided_operation_id=None,
            restored_operation_id=operation_id,
            restored_at=_now_utc(),
        )
        .where(HerdTracking.id.in_(ids))
        .execute()
    )


BUYER_REMOVED = "Köparen har begärt radering eller gallrats; registrera inte på nytt."


def attach_buyer(row, buyer, user):
    """
    WHITELISTED in-place UPDATE #3: a proof shows the buyer outside the association of a sale registered without
    one (the legacy form): a BuyerContact is made, five years from the sale's date, and set on the row. The audit
    trigger records the id on the row. Never on a row that has a buyer or that is not a sale into GX1/MX1. Once
    the five years have passed: None, and the row is marked buyer_removed instead.
    """
    fields = buyer_contact_fields(buyer, row.herd_tracking_date)
    if row.holder_contact_id is not None:
        raise HerdTrackingConflict("Försäljningen har redan en köpare. Genbanksansvarig ändrar den.")
    if row.buyer_removed:  # an erased or purged buyer is never registered again from a paper
        raise HerdTrackingConflict(BUYER_REMOVED)
    if row.voided_at is not None or row.herd.herd not in OUTSIDE_GENEBANK_HERDS:
        raise HerdTrackingInvalid("Köparens namn och ort registreras bara vid försäljning utanför genbanken.")
    contact = _new_buyer(fields, user, row.herd_tracking_date)
    HerdTracking.update(holder_contact=contact, buyer_removed=contact is None).where(
        HerdTracking.id == row.id, HerdTracking.holder_contact.is_null(True)
    ).execute()
    queue_buyer_mails(contact, row)
    return contact


def operation_individual_ids(operation_id):
    """Ids of every individual an operation wrote, voided or restored rows for (ascending)."""
    op = new_operation_id(operation_id)
    touched = HerdTracking.select(HerdTracking.individual).where(_touched_by(op)).distinct()
    return sorted({r.individual_id for r in touched})


def _operation_effects(rows, operation_id):
    """(written, voided, restored): the three effects of an operation among `rows`."""
    return (
        [r for r in rows if r.operation_id == operation_id],
        [r for r in rows if r.voided_operation_id == operation_id],
        [r for r in rows if r.restored_operation_id == operation_id],
    )


def _effects_changed_later(written, restored):
    """
    A later operation voided a row this one wrote or restored, or restored a row it wrote. The last
    case is a redo (undo of our undo): the row's void trace is gone, restored_operation_id is all
    that is left, and undoing again would only half-revert.
    """
    return [r for r in written if r.voided_at is not None or r.restored_operation_id is not None] + [
        r for r in restored if r.voided_at is not None
    ]


def _operation_time(written, voided, restored):
    return max([r.created_at for r in written] + [r.voided_at for r in voided] + [r.restored_at for r in restored])


def _touched_after(operation_id, op_time):
    """SQL: a row another operation created, voided or restored after `op_time`."""
    return (
        ((HerdTracking.operation_id != operation_id) & (HerdTracking.created_at > op_time))
        | ((HerdTracking.voided_operation_id != operation_id) & (HerdTracking.voided_at > op_time))
        | ((HerdTracking.restored_operation_id != operation_id) & (HerdTracking.restored_at > op_time))
    )


def _row_touched_after(row, operation_id, op_time):
    """Pure-Python mirror of `_touched_after` for the history hint."""
    return (
        (row.operation_id != operation_id and row.created_at > op_time)
        or (row.voided_at is not None and row.voided_operation_id != operation_id and row.voided_at > op_time)
        or (row.restored_at is not None and row.restored_operation_id != operation_id and row.restored_at > op_time)
    )


def undo_herd_tracking_operation(operation_id, user, reason, undo_operation_id=None):
    """
    Undo a whole operation atomically by inverting its three effects: void
    the rows it wrote, re-void the rows it restored (it was an undo itself), and clear
    the void fields on the rows it voided (recording this undo as their restorer).
    Refuses (409) if a later operation changed its rows, or created, voided or restored
    any row of the same individuals (a later mutation could have overwritten the
    restore trace this undo relies on). Manager/admin of every affected genebank; the permission check runs
    before the idempotent replay.

    Known limitation: a row restored here gets `voided_operation_id` cleared, so
    replaying the ORIGINAL void operation id later finds no trace of it and can void
    the row again.
    """
    op = new_operation_id(operation_id)
    cleaned = require_reason(reason)
    undo_op = new_operation_id(undo_operation_id)
    # undo_op's own rows: a replay still finds its individuals once op left no trace (a void-only op).
    ind_ids = sorted(set(operation_individual_ids(op)) | set(operation_individual_ids(undo_op)))
    if not ind_ids:
        raise HerdTrackingNotFound("Åtgärden finns inte.")
    with DB_PROXY.atomic():
        # The rows this undo may void: those the operation wrote or restored.
        redone = (HerdTracking.operation_id == op) | (HerdTracking.restored_operation_id == op)
        items = buyer_items(HerdTracking.select().where(redone), lock=True)
        lock_individuals(ind_ids)
        _require_same_items(HerdTracking.select().where(redone), items)
        individuals = {i.id: i for i in Individual.select().where(Individual.id.in_(ind_ids))}
        if any(not is_manager_of(user, i.origin_herd.genebank_id) for i in individuals.values()):
            raise HerdTrackingForbidden("Bara genbanksansvarig eller administratör kan ångra en åtgärd.")
        if _operation_rows(ind_ids, undo_op):
            return {"undo_operation_id": str(undo_op), "individual_ids": ind_ids}
        if any(i.voided for i in individuals.values()):
            raise HerdTrackingConflict("Kaninen är avpromoverad — åtgärden kan inte ångras här.")
        _reject_buyer_name([cleaned], ind_ids)
        in_locked_set = HerdTracking.individual.in_(ind_ids)
        touched = list(HerdTracking.select().where(in_locked_set, _touched_by(op)))
        written, unvoid, restored = _operation_effects(touched, op)
        if not written and not unvoid and not restored:
            raise HerdTrackingNotFound("Åtgärden finns inte eller är redan ångrad.")
        stale = _effects_changed_later(written, restored)
        if stale:
            raise HerdTrackingConflict("En senare åtgärd har redan ändrat raderna.", rows=[_row_ref(r) for r in stale])
        op_time = _operation_time(written, unvoid, restored)
        later = list(HerdTracking.select().where(in_locked_set, _touched_after(op, op_time)))
        if later:
            raise HerdTrackingConflict("En senare åtgärd finns för samma kanin.", rows=[_row_ref(r) for r in later])
        revoid = written + restored
        revoid_ids = {r.id for r in revoid}
        for ind_id in ind_ids:  # check the result BEFORE writing: an unvoid can collide with a unique index
            before = _active_rows(ind_id)
            after = [r for r in before if r.id not in revoid_ids] + [r for r in unvoid if r.individual_id == ind_id]
            if not user.is_admin and _moves_across_genebanks(individuals[ind_id], before, after):
                raise HerdTrackingForbidden(GENEBANK_CHANGE_ADMIN_ONLY)
            _assert_no_new_violations(individuals[ind_id], before, after)
            if _decouples_birth(individuals[ind_id], after):
                raise HerdTrackingConflict(
                    "Ångringen skulle ge kaninen en födelserad som inte stämmer med ursprungsbesättning "
                    "och födelsedatum. Ändra ursprungsbesättning eller födelsedatum på kaninen i stället.",
                    rows=[_row_ref(r) for r in written + unvoid if r.individual_id == ind_id and r.kind == "BIRTH"],
                )
        try:
            with DB_PROXY.atomic():
                voided = _void_rows(revoid, user, cleaned, undo_op)  # voids first: the unvoids may reuse a slot
                _unvoid_rows(unvoid, undo_op)
                for row in unvoid:  # a restored sale's buyer goes five years after that sale's date again
                    if row.holder_contact_id:
                        _set_buyer_sale_date(row.holder_contact_id, row.herd_tracking_date)
                paths = _drop_orphan_buyers(voided, VOID_ACTION, user)
        except IntegrityError as exc:
            if _violated_constraint(exc) not in ("idx_herdtracking_one_birth", "idx_herdtracking_report_attestation"):
                raise
            raise HerdTrackingConflict(
                "Ångringen skulle ge kaninen två aktiva rader där bara en är tillåten.",
                rows=[_row_ref(r) for r in unvoid],
            ) from exc
    _remove_after_commit(paths)
    return {"undo_operation_id": str(undo_op), "individual_ids": ind_ids}


OUTSIDE_LABEL = "Såld utanför genbanken"


def can_see_buyer(user, genebank_id):
    """Buyer identity (ADR-0016): admin, and a manager or helper of the genebank. Everyone else sees OUTSIDE_LABEL."""
    return is_manager_of(user, genebank_id) or genebank_id in (user.is_helper or [])


def _load_buyer_contact(contact_id, buyer_keys=None):
    """
    {"id", "name", "town"} for a BuyerContact id, never its contact details; None once erased. From `buyer_keys`
    (_buyer_keys) when the caller has them.
    """
    if buyer_keys is not None and contact_id in buyer_keys:
        stored = buyer_keys[contact_id]
        return {"id": contact_id, "name": stored[0], "town": stored[1]} if stored else None
    contact = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    return {"id": contact.id, "name": contact.name, "town": contact.town} if contact else None


def resolve_buyer(row, user, genebank_id, buyer_keys=None):
    if row.holder_contact_id is None or not can_see_buyer(user, genebank_id):
        return None
    contact = _load_buyer_contact(row.holder_contact_id, buyer_keys)
    if contact is not None:
        log_buyer_read(contact["id"], user)
    return contact


BUYER_READ_EVERY = timedelta(hours=1)  # as utils.inbox.OPENED_EVERY: a reload does not fill the log


def _audit_user(user):
    """The name audit_log's trigger records for the request's user (herdbook.before_request)."""
    return user.username or user.email


def log_buyer_contact(contact_id, operation, action, user=None, fields=None):
    """One audit_log row about a buyer: the contact id, what happened and who, never a value (ADR-0016)."""
    AuditLog.create(
        table_name=BuyerContact._meta.table_name,
        record_id=str(contact_id),
        operation=operation,
        new_data={"action": action},
        changed_fields=fields,
        changed_by=_audit_user(user) if user is not None else None,
    )


def log_buyer_read(contact_id, user):
    """Who read which buyer is logged, at most once an hour per user and buyer (as utils.inbox.open_item)."""
    seen = AuditLog.select().where(
        (AuditLog.table_name == BuyerContact._meta.table_name)
        & (AuditLog.record_id == str(contact_id))
        & (AuditLog.operation == "READ")
        & (AuditLog.changed_by == _audit_user(user))
        & (AuditLog.changed_at > _now_utc() - BUYER_READ_EVERY)
    )
    if not seen.exists():
        log_buyer_contact(contact_id, "READ", "last", user)


BUYER_TEXT_FIELDS = {
    "name": "Köparens namn",
    "town": "Ort",
    "postal_address": "Postadress",
    "email": "E-post",
    "phone": "Telefon",
}
BUYER_TEXT_MAX = 200
CONTACT_OR_MEMBERSHIP_NEEDED = (
    "E-post och telefon sparas bara om köparen har kryssat ja till att föreningen får spara dem "
    "eller kontakta köparen om medlemskap."
)


def buyer_contact_fields(buyer, sale_date, address_required=False):
    """
    The BuyerContact columns from a sale's `buyer` object: name and town required, postal_address too when
    `address_required`; email and phone only with contact_consent or membership_optin (ADR-0016). Swedish 400s.
    """
    if not isinstance(buyer, dict):
        raise HerdTrackingInvalid("Köparens uppgifter ska skickas som ett objekt.")
    fields = {}
    for key, label in BUYER_TEXT_FIELDS.items():
        value = buyer.get(key)
        if value is not None and not isinstance(value, str):
            raise HerdTrackingInvalid(f"{label} ska vara text.")
        value = (value or "").strip()
        if len(value) > BUYER_TEXT_MAX:
            raise HerdTrackingInvalid(f"{label} får vara högst {BUYER_TEXT_MAX} tecken.")
        fields[key] = value or None
    if not fields["name"] or not fields["town"]:
        raise HerdTrackingInvalid("Ange köparens namn och ort.")
    if address_required and not fields["postal_address"]:
        raise HerdTrackingInvalid("Ange köparens postadress.")
    if fields["email"] and not is_address(fields["email"]):  # or the buyer's mails are cancelled when they go
        raise HerdTrackingInvalid("Ange en e-postadress till köparen, bara adressen och bara en.")
    for key in ("name", "town"):  # the name goes into a mail from the association: never a link or a contact
        message = f"{BUYER_TEXT_FIELDS[key]} får inte innehålla en länk, en e-postadress eller ett telefonnummer."
        try:
            reject_contact_details(fields[key], links=True)
        except HerdTrackingInvalid:
            raise HerdTrackingInvalid(message) from None
    address = fields["postal_address"] or ""
    phone = any(len(re.sub(r"\D", "", m.group(0))) >= _PHONE_MIN_DIGITS for m in _PHONE.finditer(address))
    if _LINK.search(address) or _EMAIL.search(address) or phone:  # no way round the yes; a postcode is no phone
        raise HerdTrackingInvalid("Postadress får inte innehålla en länk, en e-postadress eller ett telefonnummer.")
    consent, optin = buyer.get("contact_consent", False), buyer.get("membership_optin", False)
    if not isinstance(consent, bool) or not isinstance(optin, bool):
        raise HerdTrackingInvalid("Köparens kryss ska vara ja eller nej.")
    if (fields["email"] or fields["phone"]) and not (consent or optin):
        raise HerdTrackingInvalid(CONTACT_OR_MEMBERSHIP_NEEDED)
    fields["contact_consent_at"] = _now_utc() if consent else None
    fields["membership_optin_at"] = _sale_midnight(sale_date) if optin else None
    return fields


def _name_patterns(name):
    """
    The whole name, its parts joined by spaces, hyphens or apostrophes as written ("Li-Bo", "O'Neil"), and each
    word of it of four letters or more ("per" in "Per Ström" is an ordinary word), all as whole words, also in
    the genitive.
    """
    words = re.findall(r"\w+", name)
    parts = [r"[\s'’-]+".join(map(re.escape, words))] + [re.escape(w) for w in words if len(w) >= 4]
    return [re.compile(rf"(?<!\w){part}s?(?!\w)", re.IGNORECASE) for part in parts if part]


def _holds_buyer(individual_id):
    """A row of the rabbit, live or voided, holds a buyer outside the association: what _reject_buyer_name reads."""
    return (
        HerdTracking.select()
        .where(HerdTracking.individual == individual_id, HerdTracking.holder_contact.is_null(False))
        .exists()
    )


def _reject_buyer_name(texts, individual_ids, names=()):
    """
    No buyer's name in what a user types (it lives forever in audit_log): the whole name of a buyer the rabbits'
    rows hold, or of `names`, or a word of it of four letters or more, in any case and also in the genitive.
    "Anna" stops "Annas köpare", not "annan"; "per" in "Per Ström" stops nothing alone.
    """
    texts = [text for text in texts if text]
    if not texts:
        return
    held = HerdTracking.select(HerdTracking.holder_contact).where(HerdTracking.individual.in_(individual_ids))
    stored = BuyerContact.select(BuyerContact.name).where(BuyerContact.id.in_(held))
    for name in [*names, *(name for (name,) in stored.tuples())]:
        if any(pattern.search(text) for pattern in _name_patterns(name) for text in texts):
            raise HerdTrackingInvalid(BUYER_PRIVACY_HELP)


def sold_on(sale, later):
    """
    SQL: `later` (an alias of HerdTracking) is an active row after `sale` that gives the rabbit another holder: a
    TRANSFER or CORRECTION to another herd, or to another buyer outside the association.
    """
    return (
        later.voided_at.is_null(True)
        & later.kind.in_(("TRANSFER", "CORRECTION"))
        & (
            (later.herd != sale.herd)
            | later.holder_contact.is_null(True)
            # IS DISTINCT FROM: a buyerless sale (NULL) followed by a resale with a buyer is sold on too.
            | Expression(later.holder_contact, "IS DISTINCT FROM", sale.holder_contact)
        )
        & (
            (later.herd_tracking_date > sale.herd_tracking_date)
            | ((later.herd_tracking_date == sale.herd_tracking_date) & (later.id > sale.id))
        )
    )


def delete_buyer_contacts(contact_ids, action, user=None, whole_items=False):
    """
    Deletes buyers outside the association, in the caller's transaction: on a void of the sale, an erasure, the
    rabbit's death and the five-year purge. The sale's holder_contact_id goes NULL (ON DELETE SET NULL); the sale
    stays. Each deletion is one audit_log row without personal data, and the sale's documents in the queue are
    cleared (inbox_purge.erase_buyer_from_inbox; `whole_items` on an erasure on request). Returns how many went and
    the paths for inbox_purge.remove_originals after the commit.
    """
    # Imported here: inbox_purge imports inbox, which imports individual_number_v2, which imports this module.
    from utils.inbox_purge import erase_buyer_from_inbox  # pylint: disable=import-outside-toplevel

    ids = sorted(set(contact_ids))
    if not ids:
        return 0, []
    paths = []
    sales = list(HerdTracking.select().where(HerdTracking.holder_contact.in_(ids)))
    kept = set()
    if action == "gallring_fem_ar":
        # Only voided sales hold a buyer kept across Dra tillbaka. An active sale has the five-year deadline.
        kept = {s.holder_contact_id for s in sales} - {s.holder_contact_id for s in sales if s.voided_at is None}
    # WHITELISTED in-place UPDATE #4: only permanent removals block a new buyer after an undo.
    if removed := set(ids) - kept:
        HerdTracking.update(buyer_removed=True).where(HerdTracking.holder_contact.in_(removed)).execute()
    # Every queue item the erasures below touch, locked at once in id order (the queue's order): one sale after
    # another would lock them out of order, and the nightly purge could deadlock with a correction.
    buyer_items(sales, lock=True)
    for sale in sales:  # the sales first: the delete nulls their link
        paths += erase_buyer_from_inbox(sale.id, whole_items)
    deleted = BuyerContact.delete().where(BuyerContact.id.in_(ids)).returning(BuyerContact.id).tuples()
    deleted = [contact_id for (contact_id,) in deleted]
    for contact_id in deleted:
        forget_recipient("buyer_contact", contact_id)
        log_buyer_contact(contact_id, "DELETE", "gallring_kvar" if contact_id in kept else action, user)
    return len(deleted), paths


def _transfer_confirmed(transfer_id):
    """Phase 10 seam: whether the buyer confirmed the Transfer. None until Phase 10 creates the table."""
    return None


def _herd_ref(herd):
    if herd is None:
        return {"id": None, "herd": None, "herd_name": None, "outside_genebank": False, "label": "Okänd besättning"}
    outside = herd.herd in OUTSIDE_GENEBANK_HERDS
    if outside:
        label = OUTSIDE_LABEL
    else:
        label = f"{herd.herd} – {herd.herd_name}" if herd.herd_name else herd.herd
    name = None if outside else herd.herd_name  # an outside holder's name never reaches a reader
    return {"id": herd.id, "herd": herd.herd, "herd_name": name, "outside_genebank": outside, "label": label}


def compute_periods(active_rows, herds):
    """Periods (chronological): BIRTH/TRANSFER/CORRECTION open a period, ATTESTATIONs are evidence within it."""
    periods = []
    for row in sorted(active_rows, key=ht_sort_key):
        day = coerce_date(row.herd_tracking_date).isoformat()
        if row.kind in HOLDER_CHANGING_KINDS or not periods:
            if periods:
                periods[-1]["to_date"] = day
            periods.append(
                {
                    "herd": _herd_ref(herds.get(row.herd_id)),
                    "from_date": day,
                    "to_date": None,
                    "start_kind": row.kind,
                    "start_row_id": row.id,
                    "attestation_ids": [],
                }
            )
        if row.kind == "ATTESTATION":
            periods[-1]["attestation_ids"].append(row.id)
    return periods


def _keeps_invariants(individual, before, after, known=None, buyer_keys=None):
    """
    Pure-Python mirror of the services' delta check (I1-I5), so a hint never promises a 409. `known`: the
    violations of `before`, when the caller has them (herd_tracking_history checks them once per call).
    """
    if known is None:
        known = {(v.code, v.row_id) for v in check_invariants(individual, before, buyer_keys)}
    if any((v.code, v.row_id) not in known for v in check_invariants(individual, after, buyer_keys)):
        return False
    return not (any(r.kind == "BIRTH" for r in before) and not any(r.kind == "BIRTH" for r in after))


def _operation_undo_hint(operation_id, rows, individual, known=None, buyer_keys=None):
    """UI hint only (the undo service re-checks across all individuals): undoable within this individual."""
    written, voided, restored = _operation_effects(rows, operation_id)
    if not written and not voided and not restored:
        return False
    if _effects_changed_later(written, restored):
        return False
    if written and not voided and not restored and (len(written) == 1 or all(r.kind == "BIRTH" for r in written)):
        return False  # one row, nothing voided: plain Ångra is identical; BIRTH-only: would break I5
    op_time = _operation_time(written, voided, restored)
    if any(_row_touched_after(r, operation_id, op_time) for r in rows):
        return False
    revoid_ids = {r.id for r in written + restored}
    active = [r for r in rows if r.voided_at is None]
    after = [r for r in active if r.id not in revoid_ids] + voided
    if not _keeps_invariants(individual, active, after, known, buyer_keys):
        return False
    # The service refuses a decoupled BIRTH.
    return not (any(r.kind == "BIRTH" for r in written + voided + restored) and _decouples_birth(individual, after))


def _void_keeps_invariants(individual, active, row, known=None, buyer_keys=None):
    """Pure-Python mirror of void_herd_tracking's delta check, so can_void never promises a 409 (I1-I5)."""
    return _keeps_invariants(individual, active, [r for r in active if r.id != row.id], known, buyer_keys)


def _iso(value):
    return value.isoformat() if value else None


def herd_tracking_history(individual, user, include_voided=None):
    """The v2 history payload. Rows in ht_order_desc(); periods from active rows."""
    genebank_id = individual.origin_herd.genebank_id
    can_manage = is_manager_of(user, genebank_id)
    show_voided = can_manage if include_voided is None else bool(include_voided)
    rows = list(HerdTracking.select().where(HerdTracking.individual == individual.id).order_by(*ht_order_desc()))
    herd_ids = sorted({r.herd_id for r in rows if r.herd_id} | {r.from_herd_id for r in rows if r.from_herd_id})
    herds = {h.id: h for h in Herd.select().where(Herd.id.in_(herd_ids))} if herd_ids else {}
    for row in rows:  # prime the FK cache: the denial helpers read row.herd/from_herd without a query per row
        if row.herd_id:
            row.herd = herds[row.herd_id]
        if row.from_herd_id:
            row.from_herd = herds[row.from_herd_id]
    seller_herds = user.transfer_herd_ids()  # once per call, not per TRANSFER row
    death_op = latest_death_op(individual.id)
    owners = report_owners([r.operation_id for r in rows] + [death_op])  # once per call, not per row
    active = sorted((r for r in rows if r.voided_at is None), key=ht_sort_key)
    latest_id = active[-1].id if active else None
    buyer_keys = _buyer_keys(rows)  # once per call, as the invariants of the active rows
    known = {(v.code, v.row_id) for v in check_invariants(individual, active, buyer_keys)}
    holds_buyer = any(r.holder_contact_id for r in rows)  # _holds_buyer, on the rows already read
    out = []
    for row in rows:
        if row.voided_at is not None and not show_voided:
            continue
        is_active = row.voided_at is None
        # An active row offers its writer's operation for undo, a voided row the operation that voided it.
        undo_target = row.operation_id if is_active else row.voided_operation_id
        can_void = (
            is_active
            and void_denial(user, row, active, individual, seller_herds, owners) is None
            and _void_keeps_invariants(individual, active, row, known, buyer_keys)
        )
        row_genebank = herds[row.herd_id].genebank_id if row.herd_id else genebank_id
        out.append(
            {
                "id": row.id,
                "date": coerce_date(row.herd_tracking_date).isoformat(),
                "kind": row.kind,
                "herd": _herd_ref(herds.get(row.herd_id)),
                "from_herd": _herd_ref(herds.get(row.from_herd_id)) if row.from_herd_id else None,
                "voided_at": _iso(row.voided_at),
                "voided_reason": row.voided_reason,
                "voided_operation_id": None if is_active else str(row.voided_operation_id),
                "operation_id": str(row.operation_id),
                "created_at": _iso(row.created_at),
                "confirmed": None if row.transfer_id is None else _transfer_confirmed(row.transfer_id),
                "notes": row.notes,
                "buyer": resolve_buyer(row, user, row_genebank, buyer_keys),
                "can_void": can_void,
                # void_herd_tracking would put its system reason in place of this user's: the page asks for none
                "reason_replaced": holds_buyer and not can_see_buyer(user, row_genebank),
                "can_undo_sale": bool(
                    can_void and row.kind == "TRANSFER" and row.transfer_id is None and row.id == latest_id
                ),
                "can_undo_operation": bool(
                    can_manage
                    and not individual.voided
                    and _operation_undo_hint(undo_target, rows, individual, known, buyer_keys)
                ),
                "report": _report_ref(owners.get(str(row.operation_id))),
            }
        )
    return {
        "individual": {"id": individual.id, "number": individual.number},
        "viewer": {"can_manage": can_manage},
        "death_report": _report_ref(owners.get(str(death_op))),  # the death the rabbit page's "Ångra död" undoes
        "rows": out,
        "periods": compute_periods(active, herds),
    }


def _report_ref(report):
    """The submitted yearly report that wrote a row, for the rabbit page's link to Ändra; None if none did."""
    return None if report is None else {"herd": report.herd.herd, "year": report.round.report_year}
