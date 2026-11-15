"""
The buyer outside the association (ADR-0016): erasure on request or objection, and the nightly retention.

Registration, visibility and the deletion on a void live with the sale in utils.herd_tracking. Every rule takes
`now` and is idempotent; each erasure or purge writes one audit_log row without personal data.
"""

import logging
from datetime import timedelta

from peewee import Case, fn

from utils.database import DB_PROXY, BuyerContact, HerdTracking, Individual, ht_sort_key, lock_individuals
from utils.herd_tracking import (
    QUEUE_CHANGED,
    HerdTrackingConflict,
    HerdTrackingForbidden,
    HerdTrackingNotFound,
    buyer_items,
    can_see_buyer,
    delete_buyer_contacts,
    is_manager_of,
    log_buyer_contact,
    log_buyer_read,
    sold_on,
)
from utils.inbox_purge import remove_originals
from utils.mail import forget_recipient

logger = logging.getLogger("herdbook.buyer_contact")

MEMBERSHIP_OPTIN_FOR = timedelta(days=365)  # at most 12 months


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
    Deletes the buyers among `candidates` (a query of ids) that are still `eligible` (a condition on BuyerContact)
    under a correction's locks, in its order: the queue's items, then the rabbits, both in id order. What was
    read before the locks only picks the candidates; a correction that moved a sale's date, and its purge_at, or
    cleared a death in the meantime keeps its buyer. Items that appeared under the rabbit lock leave the run to
    the next night rather than lock out of order. Returns how many went and the paths for remove_originals.
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
    still = BuyerContact.select(BuyerContact.id).where(BuyerContact.id.in_(ids) & eligible)
    return delete_buyer_contacts([contact_id for (contact_id,) in still.tuples()], action)


def purge_expired(now):
    """Name and town five years after the sale: the buyer goes."""
    expired = BuyerContact.purge_at <= now
    with DB_PROXY.atomic():
        count, paths = _delete_under_locks(
            BuyerContact.select(BuyerContact.id).where(expired), expired, "gallring_fem_ar"
        )
    remove_originals(paths)
    return count


def _held_by_dead():
    """The buyers held by a row of a rabbit recorded as dead."""
    dead = (Individual.death_date.is_null(False)) | (fn.COALESCE(Individual.death_note, "") != "")
    return (
        HerdTracking.select(HerdTracking.holder_contact)
        .join(Individual, on=(Individual.id == HerdTracking.individual))
        .where(HerdTracking.holder_contact.is_null(False) & dead)
    )


def purge_dead(now):  # pylint: disable=unused-argument  # every rule takes the clock
    """Once the association learns the rabbit is dead, its buyers' names and towns go before the five years."""
    held = BuyerContact.id.in_(_held_by_dead())
    with DB_PROXY.atomic():
        count, paths = _delete_under_locks(BuyerContact.select(BuyerContact.id).where(held), held, "gallring_dod")
    remove_originals(paths)
    return count


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
                forget_recipient("buyer_contact", contact_id)
    return len(changed)


def purge_sold_on(now):  # pylint: disable=unused-argument  # every rule takes the clock
    """
    The contact consent once the rabbit has another holder: a later active TRANSFER or CORRECTION to another herd
    or another buyer. Address, e-mail and phone go with it; e-mail and phone stay while the membership yes does.
    """
    sale, later = HerdTracking, HerdTracking.alias()
    moved_on = (
        sale.select(sale.holder_contact)
        .join(later, on=(later.individual == sale.individual))
        .where(sale.holder_contact.is_null(False) & sale.voided_at.is_null(True) & sold_on(sale, later))
    )
    no_membership = BuyerContact.membership_optin_at.is_null(True)
    kept = (
        BuyerContact.postal_address.is_null(False)
        | BuyerContact.contact_consent_at.is_null(False)
        | (no_membership & (BuyerContact.email.is_null(False) | BuyerContact.phone.is_null(False)))
    )
    changes = {
        BuyerContact.postal_address: None,
        BuyerContact.contact_consent_at: None,
        BuyerContact.email: Case(None, [(no_membership, None)], BuyerContact.email),
        BuyerContact.phone: Case(None, [(no_membership, None)], BuyerContact.phone),
    }
    return _null_fields(BuyerContact.id.in_(moved_on) & kept, changes, "gallring_salld_vidare")


def purge_membership_optin(now):
    """The yes to membership contact after 12 months, with the e-mail and phone kept only for it."""
    only_for_membership = BuyerContact.contact_consent_at.is_null(True)
    changes = {
        BuyerContact.membership_optin_at: None,
        BuyerContact.email: Case(None, [(only_for_membership, None)], BuyerContact.email),
        BuyerContact.phone: Case(None, [(only_for_membership, None)], BuyerContact.phone),
    }
    return _null_fields(BuyerContact.membership_optin_at < now - MEMBERSHIP_OPTIN_FOR, changes, "gallring_medlemskap")


RULES = (purge_membership_optin, purge_sold_on, purge_dead, purge_expired)


def run(now):
    """The nightly buyer purge: every rule on its own, so one failing does not skip the others."""
    for rule in RULES:
        try:
            logger.info("Buyer purge %s: %s", rule.__name__, rule(now))
        except Exception:  # pylint: disable=broad-except
            logger.exception("Buyer purge %s failed", rule.__name__)
