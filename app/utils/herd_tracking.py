"""
Herd-tracking domain service.

Every write to herd_tracking goes through this module: it locks the individual
row, validates the invariants and groups rows into operations. data_access.py
imports this module; this module never imports data_access.py.
"""

import re
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from peewee import IntegrityError, fn

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
    Individual,
    coerce_date,
    ht_not_voided,
    ht_order_desc,
    ht_sort_key,
    lock_individuals,
)
from utils.mail import forget_recipient

UNPROMOTE_REASON = "avpromoverad"


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
    association those rows held; the caller passes them to _drop_orphan_buyers once its writes are done. A buyer
    is never named in the reason.
    """
    ids = [r.id for r in rows]
    if not ids:
        return []
    _reject_buyer_name(reason, HerdTracking.select(HerdTracking.holder_contact).where(HerdTracking.id.in_(ids)))
    voided = list(
        HerdTracking.update(
            voided_at=_now_utc(),
            voided_by_user=user,
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
        return 0
    held = HerdTracking.select(HerdTracking.holder_contact).where(
        HerdTracking.holder_contact.in_(contact_ids), ht_not_voided()
    )
    orphans = set(contact_ids) - {contact_id for (contact_id,) in held.tuples()}
    # The proofs' files go with remove_orphans: this runs inside the caller's transaction.
    return delete_buyer_contacts(orphans, action, user)[0]


def void_all_for_unpromote(individual, user, operation_id=None):
    """Retire every active row of an un-promoted individual in one operation."""
    op = new_operation_id(operation_id)
    with DB_PROXY.atomic():
        lock_individuals([individual.id])
        rows = list(HerdTracking.select().where(HerdTracking.individual == individual.id, ht_not_voided()))
        if not user.is_admin and _moves_across_genebanks(individual, rows, []):
            raise HerdTrackingForbidden(GENEBANK_CHANGE_ADMIN_ONLY)
        _drop_orphan_buyers(_void_rows(rows, user, UNPROMOTE_REASON, op), VOID_ACTION, user)
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


def check_invariants(individual, rows):
    """I1–I4 over one individual's ACTIVE rows; returns a set of Violation."""
    ordered = sorted(rows, key=ht_sort_key)
    found = set()
    births = [r for r in ordered if r.kind == "BIRTH"]
    for extra in births[1:]:
        found.add(Violation("I1", extra.id, "Kaninen har mer än en aktiv födelserad."))
    birth_date = coerce_date(births[0].herd_tracking_date) if births else None
    holder = individual.origin_herd_id
    for row in ordered:
        day = coerce_date(row.herd_tracking_date)
        if birth_date and day < birth_date:
            found.add(Violation("I3", row.id, f"Händelsen {day} ligger före födelseraden {birth_date}."))
        if row.kind == "ATTESTATION" and row.herd_id != holder:
            found.add(Violation("I2", row.id, "En årsrapport måste gälla besättningen som har kaninen vid datumet."))
        if row.kind in ("TRANSFER", "CORRECTION") and row.herd_id == holder and not _outside_resale(row):
            found.add(Violation("I4", row.id, "En flytt måste gå till en annan besättning än den som har kaninen."))
        if row.kind in HOLDER_CHANGING_KINDS:
            holder = row.herd_id
    return found


def _outside_resale(row):
    """
    ADR-0016's one exception to I4: a TRANSFER within GX1/MX1, a buyer outside the association selling to another.
    Kept when the buyers are erased later, so the herd decides, not holder_contact_id; record_herd_tracking writes
    one only with a new buyer.
    """
    return row.kind == "TRANSFER" and row.herd_id is not None and row.herd.herd in OUTSIDE_GENEBANK_HERDS


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
):
    """
    The central writer. Locks the individual, re-reads its
    active rows, requires date >= the latest active row (except BIRTH), sets
    from_herd to the holder at the date, checks I1–I4 as a delta and writes.
    Idempotent per (individual, operation_id). `buyer` (a sale to GX1/MX1 only) is the buyer outside the
    association as buyer_contact_fields reads it, stored with the row in the same transaction.
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
    if buyer is not None and (kind != "TRANSFER" or target.herd not in OUTSIDE_GENEBANK_HERDS):
        raise HerdTrackingInvalid("Köparens namn och ort registreras bara vid försäljning utanför genbanken.")
    contact_fields = buyer_contact_fields(buyer) if buyer is not None else None
    individual_id = individual.id if isinstance(individual, Individual) else int(individual)
    with DB_PROXY.atomic():
        lock_individuals([individual_id])
        ind = Individual.get_by_id(individual_id)
        done = _operation_rows([individual_id], op)
        if done:
            return next((r for r in done if r.operation_id == op), done[0])
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
        contact = BuyerContact.create(**contact_fields, created_by_user=user) if contact_fields else None
        try:
            with DB_PROXY.atomic():
                row = HerdTracking.create(
                    individual=individual_id,
                    herd=target,
                    from_herd=None if kind == "BIRTH" else holder_id,
                    signature=user,
                    herd_tracking_date=when,
                    kind=kind,
                    operation_id=op,
                    notes=notes,
                    yearly_herd_report=yearly_herd_report,
                    transfer_id=transfer_id,
                    holder_contact=contact,
                )
        except IntegrityError as exc:
            if _violated_constraint(exc) != "idx_herdtracking_report_attestation":
                raise
            raise HerdTrackingConflict("Kaninen har redan en aktiv rad för den här rapporten.") from exc
        if contact is not None:
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
        voided = _void_rows([birth], user, reason, op)
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
        _drop_orphan_buyers(voided, VOID_ACTION, user)
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


def reject_contact_details(text):
    """No buyer identity in free text: it lives forever in audit_log."""
    if not text:
        return
    if _EMAIL.search(text) or any(
        len(re.sub(r"\D", "", m.group(0))) >= _PHONE_MIN_DIGITS for m in _PHONE.finditer(text)
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


def void_denial(user, row, active_rows, individual, transfer_herd_ids=None):
    """The void permission table. None = allowed."""
    if row.kind == "BIRTH":
        return "En födelserad kan inte ångras — den kan bara ersättas."
    if not user.is_admin and _moves_across_genebanks(individual, active_rows, [r for r in active_rows if r != row]):
        return GENEBANK_CHANGE_ADMIN_ONLY
    if is_manager_of(user, _row_genebank_id(row, individual)):
        return None
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


def void_herd_tracking(ht_id, user, reason, operation_id=None):
    """
    Void one row (also "Ångra försäljning"). Idempotent per (individual, operation_id):
    a replayed operation returns the row it voided; an already voided row is a no-op.
    Checks I1–I5 afterwards. Callers must gate READ access first: the idempotent
    replay returns before the permission check.
    """
    cleaned = require_reason(reason)
    op = new_operation_id(operation_id)
    row = HerdTracking.get_or_none(HerdTracking.id == ht_id)
    if row is None:
        raise HerdTrackingNotFound("Raden finns inte.")
    with DB_PROXY.atomic():
        lock_individuals([row.individual_id])
        done = _operation_rows([row.individual_id], op)
        if done:
            return next((r for r in done if r.voided_operation_id == op), done[0])
        row = HerdTracking.get_by_id(ht_id)
        if row.voided_at is not None:
            return row
        individual = Individual.get_by_id(row.individual_id)
        before = _active_rows(individual.id)
        denial = void_denial(user, row, before, individual)
        if denial:
            raise HerdTrackingForbidden(denial)
        voided = _void_rows([row], user, cleaned, op)
        _assert_no_new_violations(individual, before, [r for r in before if r.id != row.id])
        _drop_orphan_buyers(voided, VOID_ACTION, user)
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
        # The sale's buyer outside the association: one kept from a row voided here, or a new one (the queue).
        contact, buyer = event.get("holder_contact_id"), event.get("buyer")
        if (contact is not None or buyer is not None) and (
            (contact is not None and (not isinstance(contact, int) or isinstance(contact, bool)))
            or (contact is not None and buyer is not None)
            or kind != "TRANSFER"
            or herd.herd not in OUTSIDE_GENEBANK_HERDS
        ):
            raise HerdTrackingInvalid(f"Händelse {number}: en köpare hör bara till en försäljning utanför genbanken.")
        parsed.append(
            {
                "date": when,
                "herd": herd,
                "kind": kind,
                "notes": notes,
                "holder_contact_id": contact,
                "buyer": buyer_contact_fields(buyer) if buyer is not None else None,
            }
        )
        previous = when
    return parsed


def _holder_before(individual, rows, when, kind):
    """Holder just before an event inserted at (when, kind) — any row kind counts."""
    key = (when, 0 if kind == "BIRTH" else 1, float("inf"))
    prior = [r for r in sorted(rows, key=ht_sort_key) if ht_sort_key(r) < key]
    return prior[-1].herd_id if prior else individual.origin_herd_id


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
        lock_individuals([ind_id])
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
        # A rewritten sale keeps its buyer, with the original purge_at: only one a row voided here held.
        released = {by_id[v].holder_contact_id for v in void_ids} - {None}
        if any(e["holder_contact_id"] not in released for e in parsed if e["holder_contact_id"] is not None):
            raise HerdTrackingInvalid("En köpare kan bara flyttas från en rad som ångras i samma korrigering.")
        voided = _void_rows([by_id[v] for v in void_ids], user, cleaned, op)
        written, current = [], list(kept)
        for event in parsed:
            birth = event["kind"] == "BIRTH"
            from_herd = None if birth else _holder_before(ind, current, event["date"], event["kind"])
            # GX1 to GX1 only with a new buyer (record_herd_tracking); elsewhere I4 below answers.
            if (
                event["kind"] == "TRANSFER"
                and from_herd == event["herd"].id
                and event["herd"].herd in OUTSIDE_GENEBANK_HERDS
                and event["holder_contact_id"] is None
                and event["buyer"] is None
            ):
                detail = "En flytt måste gå till en annan besättning än den som har kaninen."
                raise HerdTrackingConflict(detail, rows=[{"id": None, "code": "I4", "detail": detail}])
            row = HerdTracking.create(
                individual=ind_id,
                herd=event["herd"],
                from_herd=from_herd,
                signature=user,
                herd_tracking_date=event["date"],
                kind=event["kind"],
                operation_id=op,
                notes=event["notes"],
                holder_contact=(
                    BuyerContact.create(**event["buyer"], created_by_user=user)
                    if event["buyer"]
                    else event["holder_contact_id"]
                ),
            )
            if event["buyer"]:
                queue_buyer_mails(row.holder_contact, row)
            written.append(row)
            current.append(row)
        # Admin only (rolled back). An event's herd is in the origin genebank, but the holder before it may
        # not be: its reason is the row's note.
        if not user.is_admin and _moves_across_genebanks(ind, before, current):
            raise HerdTrackingForbidden(GENEBANK_CHANGE_ADMIN_ONLY)
        if any(_changes_genebank(r, ind, current) and not r.notes for r in written):
            raise HerdTrackingInvalid("Ange en anledning i anteckningen för ett genbanksbyte.")
        _assert_no_new_violations(ind, before, current)
        _drop_orphan_buyers(voided, VOID_ACTION, user)
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
            voided_reason=None,
            voided_operation_id=None,
            restored_operation_id=operation_id,
            restored_at=_now_utc(),
        )
        .where(HerdTracking.id.in_(ids))
        .execute()
    )


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
        lock_individuals(ind_ids)
        individuals = {i.id: i for i in Individual.select().where(Individual.id.in_(ind_ids))}
        if any(not is_manager_of(user, i.origin_herd.genebank_id) for i in individuals.values()):
            raise HerdTrackingForbidden("Bara genbanksansvarig eller administratör kan ångra en åtgärd.")
        if _operation_rows(ind_ids, undo_op):
            return {"undo_operation_id": str(undo_op), "individual_ids": ind_ids}
        if any(i.voided for i in individuals.values()):
            raise HerdTrackingConflict("Kaninen är avpromoverad — åtgärden kan inte ångras här.")
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
                _drop_orphan_buyers(voided, VOID_ACTION, user)
        except IntegrityError as exc:
            if _violated_constraint(exc) not in ("idx_herdtracking_one_birth", "idx_herdtracking_report_attestation"):
                raise
            raise HerdTrackingConflict(
                "Ångringen skulle ge kaninen två aktiva rader där bara en är tillåten.",
                rows=[_row_ref(r) for r in unvoid],
            ) from exc
    return {"undo_operation_id": str(undo_op), "individual_ids": ind_ids}


OUTSIDE_LABEL = "Såld utanför genbanken"


def can_see_buyer(user, genebank_id):
    """Buyer identity (ADR-0016): admin, and a manager or helper of the genebank. Everyone else sees OUTSIDE_LABEL."""
    return is_manager_of(user, genebank_id) or genebank_id in (user.is_helper or [])


BUYER_SHOWN = ("name", "town", "postal_address", "email", "phone")


def _load_buyer_contact(contact_id):
    """{"id", "name", "town"} and the contact details that are kept, for a BuyerContact id; None once erased."""
    contact = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    if contact is None:
        return None
    shown = {key: getattr(contact, key) for key in BUYER_SHOWN if getattr(contact, key) is not None}
    return {"id": contact.id, **shown}


def resolve_buyer(row, user, genebank_id):
    if row.holder_contact_id is None or not can_see_buyer(user, genebank_id):
        return None
    contact = _load_buyer_contact(row.holder_contact_id)
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
CONTACT_CONSENT_NEEDED = (
    "Postadress, e-post och telefon sparas bara om köparen har kryssat ja till att föreningen får spara dem."
)
CONTACT_OR_MEMBERSHIP_NEEDED = (
    "E-post och telefon sparas bara om köparen har kryssat ja till att föreningen får spara dem "
    "eller kontakta köparen om medlemskap."
)


def buyer_contact_fields(buyer):
    """
    The BuyerContact columns from a sale's `buyer` object: name and town required; postal_address only with
    contact_consent, email and phone with contact_consent or membership_optin (ADR-0016). Swedish 400s.
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
    consent, optin = buyer.get("contact_consent", False), buyer.get("membership_optin", False)
    if not isinstance(consent, bool) or not isinstance(optin, bool):
        raise HerdTrackingInvalid("Köparens kryss ska vara ja eller nej.")
    if fields["postal_address"] and not consent:
        raise HerdTrackingInvalid(CONTACT_CONSENT_NEEDED)
    if (fields["email"] or fields["phone"]) and not (consent or optin):
        raise HerdTrackingInvalid(CONTACT_OR_MEMBERSHIP_NEEDED)
    now = _now_utc()
    fields["contact_consent_at"] = now if consent else None
    fields["membership_optin_at"] = now if optin else None
    return fields


def _reject_buyer_name(text, contact_ids):
    """No buyer's name in free text (it lives forever in audit_log): `contact_ids` is a list or a subquery."""
    if not text:
        return
    names = BuyerContact.select(BuyerContact.name).where(BuyerContact.id.in_(contact_ids))
    if any(name.casefold() in text.casefold() for (name,) in names.tuples()):
        raise HerdTrackingInvalid(BUYER_PRIVACY_HELP)


def delete_buyer_contacts(contact_ids, action, user=None, certificates=False):
    """
    Deletes buyers outside the association, in the caller's transaction: on a void of the sale, an erasure and
    the five-year purge. The sale's holder_contact_id goes NULL (ON DELETE SET NULL); the sale stays. Each
    deletion is one audit_log row without personal data. The sale's documents in the queue lose their originals
    (inbox_purge.erase_buyer_from_inbox; `certificates` on an erasure). Returns how many went and the paths for
    inbox_purge.remove_originals after the commit.
    """
    # Imported here: inbox_purge imports inbox, which imports individual_number_v2, which imports this module.
    from utils.inbox_purge import erase_buyer_from_inbox  # pylint: disable=import-outside-toplevel

    ids = sorted(set(contact_ids))
    if not ids:
        return 0, []
    paths = []
    # The sales first: the delete nulls their link.
    for (sale_id,) in HerdTracking.select(HerdTracking.id).where(HerdTracking.holder_contact.in_(ids)).tuples():
        paths += erase_buyer_from_inbox(sale_id, certificates=certificates)
    deleted = BuyerContact.delete().where(BuyerContact.id.in_(ids)).returning(BuyerContact.id).tuples()
    deleted = [contact_id for (contact_id,) in deleted]
    for contact_id in deleted:
        forget_recipient("buyer_contact", contact_id)
        log_buyer_contact(contact_id, "DELETE", action, user)
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


def _operation_undo_hint(operation_id, rows, individual):
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
    if any(r.kind == "BIRTH" for r in written + voided + restored):  # the service refuses a decoupled BIRTH
        revoid_ids = {r.id for r in written + restored}
        after = [r for r in rows if r.voided_at is None and r.id not in revoid_ids] + voided
        return not _decouples_birth(individual, after)
    return True


def _void_keeps_invariants(individual, active, row):
    """Pure-Python mirror of void_herd_tracking's delta check, so can_void never promises a 409 (I1-I5)."""
    after = [r for r in active if r.id != row.id]
    known = {(v.code, v.row_id) for v in check_invariants(individual, active)}
    if any((v.code, v.row_id) not in known for v in check_invariants(individual, after)):
        return False
    return not (row.kind == "BIRTH" and not any(r.kind == "BIRTH" for r in after))


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
    active = sorted((r for r in rows if r.voided_at is None), key=ht_sort_key)
    latest_id = active[-1].id if active else None
    out = []
    for row in rows:
        if row.voided_at is not None and not show_voided:
            continue
        is_active = row.voided_at is None
        # An active row offers its writer's operation for undo, a voided row the operation that voided it.
        undo_target = row.operation_id if is_active else row.voided_operation_id
        can_void = (
            is_active
            and void_denial(user, row, active, individual, seller_herds) is None
            and _void_keeps_invariants(individual, active, row)
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
                "buyer": resolve_buyer(row, user, row_genebank),
                "can_void": can_void,
                "can_undo_sale": bool(
                    can_void and row.kind == "TRANSFER" and row.transfer_id is None and row.id == latest_id
                ),
                "can_undo_operation": bool(
                    can_manage and not individual.voided and _operation_undo_hint(undo_target, rows, individual)
                ),
            }
        )
    return {
        "individual": {"id": individual.id, "number": individual.number},
        "viewer": {"can_manage": can_manage},
        "rows": out,
        "periods": compute_periods(active, herds),
    }
