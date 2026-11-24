"""
The buyer outside the association (ADR-0016): erasure on request or objection, and the nightly retention.

Registration, visibility and the deletion on a void live with the sale in utils.herd_tracking. Every rule takes
`now` and is idempotent; each erasure or purge writes one audit_log row without personal data.
"""

import logging
from datetime import datetime, timedelta, timezone

from peewee import SQL, Case, fn

import utils.sale_proposal as sale_proposal
from utils import settings
from utils.buyer_mail import lock_buyer_addresses, queue_buyer_mails
from utils.database import (
    DB_PROXY,
    MEMBERSHIP_OPTIN_FOR,
    AuditLog,
    BuyerContact,
    Herd,
    HerdTracking,
    Individual,
    MailMessage,
    SaleProposal,
    ht_sort_key,
    lock_individuals,
)
from utils.herd_tracking import (
    QUEUE_CHANGED,
    HerdTrackingConflict,
    HerdTrackingForbidden,
    HerdTrackingInvalid,
    HerdTrackingNotFound,
    buyer_address_conflicts,
    buyer_contact_fields,
    buyer_items,
    can_see_buyer,
    check_invariants,
    delete_buyer_contacts,
    is_manager_of,
    log_buyer_contact,
    log_buyer_read,
    sold_on,
)
from utils.inbox_purge import remove_originals
from utils.individual_commands import FREE_TEXT_RETENTION
from utils.mail import RETENTION as MAIL_RETENTION
from utils.mail import address_hash, forget_recipient, is_address

logger = logging.getLogger("herdbook.buyer_contact")

PROPOSAL_BUYER_FOR = FREE_TEXT_RETENTION  # spec section 6: 13 months, as the command log's free text


def buyer_genebank(contact_id):
    """The genebank of the herd of the row holding the buyer: the active row, else the latest; None without one."""
    rows = list(HerdTracking.select().where(HerdTracking.holder_contact == contact_id))
    row = max([r for r in rows if r.voided_at is None] or rows, key=ht_sort_key, default=None)
    return row.herd.genebank_id if row is not None and row.herd_id else None


def _managed_contact(contact_id, user, action):
    """
    The buyer, for admin or a manager of the genebank of the row holding it (ADR-0014): anyone who may not see the
    buyer is told it does not exist, a helper who may see it is refused.
    """
    contact = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    genebank_id = buyer_genebank(contact_id) if contact else None
    if contact is None or not (user.is_admin or (genebank_id is not None and can_see_buyer(user, genebank_id))):
        raise HerdTrackingNotFound("Köparen finns inte.")
    if not (user.is_admin or is_manager_of(user, genebank_id)):
        raise HerdTrackingForbidden(f"Bara genbanksansvarig eller administratör kan {action} köparens uppgifter.")
    return contact


CONTACT_FIELDS = ("name", "town", "postal_address", "email", "phone", "contact_consent_at", "membership_optin_at")


def read_buyer_contact(contact_id, user):
    """GET /api/v2/buyer-contacts/<id>: every kept field of the buyer, for admin and the genebank's managers; logged."""
    contact = _managed_contact(contact_id, user, "läsa")
    log_buyer_read(contact.id, user)
    values = {name: getattr(contact, name) for name in CONTACT_FIELDS}
    return {"id": contact.id, **{k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in values.items()}}


def _email_reviews(user):
    sales = (
        HerdTracking.select(HerdTracking, BuyerContact)
        .join(BuyerContact, on=(HerdTracking.holder_contact == BuyerContact.id))
        .switch(HerdTracking)
        .join(Herd, on=(HerdTracking.herd == Herd.id))
        .where(HerdTracking.voided_at.is_null(), BuyerContact.email_review_pending, BuyerContact.email.is_null(False))
    )
    return sales if user.is_admin else sales.where(Herd.genebank.in_(user.is_manager or []))


def buyer_email_reviews(number, user):
    sales = _email_reviews(user).where(
        HerdTracking.individual.in_(Individual.select(Individual.id).where(Individual.number == number))
    )
    result = []
    for sale in sales.order_by(HerdTracking.id):
        buyer = sale.holder_contact
        log_buyer_read(buyer.id, user)
        result.append({"id": buyer.id, "name": buyer.name, "email": buyer.email})
    return result


def review_buyer_email(contact_id, body, user):
    """Resolve one active sale under the rabbit, address and contact locks. A stale review cannot change a buyer."""
    with DB_PROXY.atomic():
        query = _email_reviews(user).where(HerdTracking.holder_contact == contact_id)
        sale = query.first()
        if sale is None:
            raise HerdTrackingNotFound("Det finns ingen köparadress att kontrollera.")
        lock_individuals([sale.individual_id])
        confirm = set(body) == {"confirm"} and body["confirm"] is True
        if not confirm and set(body) != {"name", "email"}:
            raise HerdTrackingInvalid("Rätta namnet eller adressen, eller bekräfta att det är samma person.")
        if not confirm and not isinstance(body["email"], str):
            raise HerdTrackingInvalid("Ange köparens e-postadress.")
        lock_buyer_addresses([sale.holder_contact.email, body.get("email")])
        sale = query.for_update(of=[BuyerContact]).first()
        if sale is None:
            raise HerdTrackingNotFound("Det finns ingen köparadress att kontrollera.")
        contact = sale.holder_contact
        changed = ["email_review_pending"]
        if not confirm:
            fields = buyer_contact_fields(
                {
                    **body,
                    "town": contact.town,
                    "contact_consent": bool(contact.contact_consent_at),
                    "membership_optin": bool(contact.membership_optin_at),
                },
                sale.herd_tracking_date,
            )
            if not fields["email"]:
                raise HerdTrackingInvalid("Ange köparens e-postadress.")
            if buyer_address_conflicts(fields["email"], fields["name"], replaces=contact.id):
                raise HerdTrackingInvalid("Adressen finns fortfarande hos en köpare med ett annat namn.")
            if contact.name != fields["name"]:
                # Name and town identify the two holders in a resale within GX1/MX1.
                rows = list(
                    HerdTracking.select().where(
                        HerdTracking.individual == sale.individual_id, HerdTracking.voided_at.is_null()
                    )
                )
                before = check_invariants(sale.individual, rows)
                contact.name = fields["name"]
                contact.save(only=[BuyerContact.name])
                if check_invariants(sale.individual, rows) - before:
                    raise HerdTrackingInvalid("Namnet skulle göra besättningshistoriken motsägelsefull.")
                changed.append("name")
            if contact.email != fields["email"]:
                contact.email = fields["email"]
                changed.append("email")
        contact.email_review_pending = False
        contact.save(only=[BuyerContact.email_review_pending, BuyerContact.email])
        log_buyer_contact(contact.id, "UPDATE", "adress_kontrollerad", user, fields=changed)
        queue_buyer_mails(contact, sale)


def erase_buyer_contact(contact_id, user):
    """
    DELETE /api/v2/buyer-contacts/<id>: every detail of the buyer goes, also name and town; the sale and its
    TRANSFER row stay.
    """
    _managed_contact(contact_id, user, "radera")
    with DB_PROXY.atomic():
        # The locks a correction takes, in its order (the queue's items, then the rabbits), so the two queue up.
        holding = list(HerdTracking.select().where(HerdTracking.holder_contact == contact_id))
        items = buyer_items(holding, lock=True)
        lock_individuals([r.individual_id for r in holding])
        if not buyer_items(holding) <= items:  # an item that appeared since: never a lock out of order
            raise HerdTrackingConflict(QUEUE_CHANGED)
        _count, paths = delete_buyer_contacts([contact_id], "radering", user, whole_items=True)
    remove_originals(paths)  # only after the commit: a row never names a removed file


def _delete_under_locks(candidates, eligible, action):
    """
    Deletes the buyers among `candidates` (a query of ids) that are still `eligible` (a function giving a condition
    on BuyerContact, called under the locks) under a correction's locks, in its order: the queue's items, then the
    rabbits, both in id order. What was read before the locks only picks the candidates; a correction that moved a
    sale's date, and its purge_at, or cleared a death in the meantime keeps its buyer. Items that appeared under the
    rabbit lock leave the run to the next night rather than lock out of order. Returns how many went and the paths
    for remove_originals.
    """
    ids = [contact_id for (contact_id,) in candidates.tuples()]
    if not ids:
        return 0, []
    holding = list(HerdTracking.select().where(HerdTracking.holder_contact.in_(ids)))
    items = buyer_items(holding, lock=True)
    lock_individuals({r.individual_id for r in holding})
    holding = list(HerdTracking.select().where(HerdTracking.holder_contact.in_(ids)))
    if not buyer_items(holding) <= items:
        logger.warning("Buyer purge %s: the queue changed under the locks; the next run takes it", action)
        return 0, []
    still = BuyerContact.select(BuyerContact.id).where(BuyerContact.id.in_(ids) & eligible()).order_by(BuyerContact.id)
    return delete_buyer_contacts([contact_id for (contact_id,) in still.for_update().tuples()], action)


def purge_expired(now):
    """Delete buyers when the five years after a sale or the keep window after withdrawal expires."""
    expired = BuyerContact.purge_at <= now
    with DB_PROXY.atomic():
        count, paths = _delete_under_locks(
            BuyerContact.select(BuyerContact.id).where(expired), lambda: expired, "gallring_fem_ar"
        )
    remove_originals(paths)
    return count


DEATH_SETTLES = timedelta(days=30)  # a death reported by mistake is usually cleared within this


def _dead_since(individual_ids, now):
    """
    The rabbits among `individual_ids` whose death has stood recorded for DEATH_SETTLES: the latest audit_log row
    that recorded the death (death_date or death_note set) is at least that old, or, recorded before the audit
    trigger, the death date is.
    """
    dead = list(
        Individual.select(Individual.id, Individual.death_date).where(Individual.id.in_(individual_ids), _dead())
    )
    recorded = {}
    entries = AuditLog.select(AuditLog.record_id, AuditLog.changed_at, AuditLog.new_data).where(
        (AuditLog.table_name == Individual._meta.table_name)
        & AuditLog.operation.in_(("INSERT", "UPDATE"))
        & AuditLog.record_id.in_([str(individual.id) for individual in dead])
        & (AuditLog.changed_fields.contains("death_date") | AuditLog.changed_fields.contains("death_note"))
    )
    for record_id, changed_at, new in entries.order_by(AuditLog.id).tuples():
        if (new or {}).get("death_date") or (new or {}).get("death_note"):
            recorded[int(record_id)] = changed_at
    settled = set()
    for individual in dead:
        at = recorded.get(individual.id)
        if at is None and individual.death_date is not None:
            at = datetime.combine(individual.death_date, datetime.min.time(), timezone.utc)
        if at is None or at.replace(tzinfo=at.tzinfo or timezone.utc) <= now - DEATH_SETTLES:
            settled.add(individual.id)
    return settled


def _dead():
    return Individual.death_date.is_null(False) | (fn.COALESCE(Individual.death_note, "") != "")


def _held_by_dead(individual_ids=None):
    """The buyers held by a row of a rabbit recorded as dead (among `individual_ids`, when given)."""
    dead = _dead()
    if individual_ids is not None:
        dead &= Individual.id.in_(list(individual_ids))
    return (
        HerdTracking.select(HerdTracking.holder_contact)
        .join(Individual, on=(Individual.id == HerdTracking.individual))
        .where(HerdTracking.holder_contact.is_null(False) & dead)
    )


def purge_dead(now):
    """
    A rabbit's buyers go before the five years once its death has stood recorded for 30 days: a death reported by
    mistake and cleared within them keeps its buyers. Rechecked under the locks, so a death cleared meanwhile does too.
    """
    candidates = {
        r.individual_id
        for r in HerdTracking.select(HerdTracking.individual).where(HerdTracking.holder_contact.in_(_held_by_dead()))
    }

    def held():  # read again under the locks: a death cleared and recorded anew meanwhile starts its 30 days over
        return BuyerContact.id.in_(_held_by_dead(_dead_since(candidates, now)))

    with DB_PROXY.atomic():
        count, paths = _delete_under_locks(BuyerContact.select(BuyerContact.id).where(held()), held, "gallring_dod")
    remove_originals(paths)
    return count


def purge_proposal_buyers(now):
    """
    Purge a pending proposal's buyer after 13 months or when the death has stood recorded for 30 days.
    Recheck each proposal under its locks so that correcting a death keeps the buyer.
    """

    def due(individual_ids):
        return (SaleProposal.created_at < now - PROPOSAL_BUYER_FOR) | SaleProposal.individual.in_(
            _dead_since(individual_ids, now)
        )

    pending = SaleProposal.select().where(SaleProposal.state == "foreslagen", SaleProposal.buyer.is_null(False))
    found = list(pending.where(due(pending.select(SaleProposal.individual))).order_by(SaleProposal.id))
    return sum(sale_proposal.clear_buyer(proposal, "gallring_forslag", still=due) for proposal in found)


def _null_fields(where, changes, action):
    """
    Nulls `changes` on the buyers matching `where`, one audit_log row each naming the columns that went (never the
    values), and the mail queue forgets an e-mail address that went; returns how many.
    """
    columns = [field.name for field in changes]
    with DB_PROXY.atomic():
        held = BuyerContact.select(BuyerContact.id, *changes).where(where)
        before = {row[0]: dict(zip(columns, row[1:], strict=True)) for row in held.for_update().tuples()}
        if not before:
            return 0
        query = BuyerContact.update(changes).where(BuyerContact.id.in_(list(before)))
        changed = list(query.returning(BuyerContact.id, *changes).tuples())
        for contact_id, *values in changed:
            after = dict(zip(columns, values, strict=True))
            gone = [name for name in columns if before[contact_id][name] is not None and after[name] is None]
            log_buyer_contact(contact_id, "UPDATE", action, fields=gone)
            if "email" in gone:
                email = before[contact_id]["email"]
                if settings.mail.link_secret and is_address(email):
                    BuyerContact.update(erased_email_hash=address_hash(email)).where(
                        BuyerContact.id == contact_id
                    ).execute()
                forget_recipient("buyer_contact", contact_id)
    return len(changed)


def _purge_consent(now, due, consent, other_consent, action):
    """Expire a consent, keeping the email while the first notice still needs it."""
    # A failed notice can be retried from the status view until purge_old_mail removes it.
    retryable = (MailMessage.status == "failed") & (MailMessage.created_at >= now - MAIL_RETENTION)
    # Peewee 3 renders a Select inside UPDATE SET ... CASE as its table alias. Keep the parameters bound.
    sql, params = (
        MailMessage.select(MailMessage.recipient_id)
        .where(
            MailMessage.recipient_kind == "buyer_contact",
            MailMessage.kind == "kopare.information",
            MailMessage.status.in_(("queued", "sending")) | retryable,
        )
        .sql()
    )
    last_consent = other_consent.is_null(True)
    # The address needs one consent under the database constraint. Only the phone can go while the notice waits.
    keep_for_notice = (
        last_consent
        & BuyerContact.email.is_null(False)
        & (BuyerContact.email_review_pending | BuyerContact.id.in_(SQL(f"({sql})", params)))
    )
    changes = {
        consent: Case(None, [(keep_for_notice, consent)], None),
        BuyerContact.email: Case(None, [(last_consent & ~keep_for_notice, None)], BuyerContact.email),
        BuyerContact.phone: Case(None, [(last_consent, None)], BuyerContact.phone),
    }
    return _null_fields(due & (~keep_for_notice | BuyerContact.phone.is_null(False)), changes, action)


def purge_sold_on(now):
    """
    The contact consent once the rabbit has another holder: a later active TRANSFER or CORRECTION to another herd
    or another buyer. The postal address stays, on legitimate interest like name and town.
    """
    sale, later = HerdTracking, HerdTracking.alias()
    moved_on = (
        sale.select(sale.holder_contact)
        .join(later, on=(later.individual == sale.individual))
        .where(sale.holder_contact.is_null(False) & sale.voided_at.is_null(True) & sold_on(sale, later))
    )
    consent = BuyerContact.contact_consent_at
    due = BuyerContact.id.in_(moved_on) & consent.is_null(False)
    return _purge_consent(now, due, consent, BuyerContact.membership_optin_at, "gallring_salld_vidare")


def purge_membership_optin(now):
    """The yes to membership contact after 12 months, with the e-mail and phone kept only for it."""
    optin = BuyerContact.membership_optin_at
    due = optin <= now - MEMBERSHIP_OPTIN_FOR
    return _purge_consent(now, due, optin, BuyerContact.contact_consent_at, "gallring_medlemskap")


RULES = (purge_membership_optin, purge_sold_on, purge_dead, purge_expired, purge_proposal_buyers)


def run(now):
    """The nightly buyer purge: every rule on its own, so one failing does not skip the others."""
    for rule in RULES:
        try:
            logger.info("Buyer purge %s: %s", rule.__name__, rule(now))
        except Exception:  # pylint: disable=broad-except
            logger.exception("Buyer purge %s failed", rule.__name__)
