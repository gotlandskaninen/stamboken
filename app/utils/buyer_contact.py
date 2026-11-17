"""
The buyer outside the association (ADR-0016): erasure on request or objection, and the nightly retention.

Registration, visibility and the deletion on a void live with the sale in utils.herd_tracking. Every rule takes
`now` and is idempotent; each erasure or purge writes one audit_log row without personal data.
"""

import logging
from datetime import timedelta

from peewee import Case, fn

from utils.database import DB_PROXY, BuyerContact, HerdTracking, Individual, ht_sort_key
from utils.herd_tracking import (
    HerdTrackingForbidden,
    HerdTrackingNotFound,
    QueueChanged,
    can_see_buyer,
    delete_buyer_contacts,
    is_manager_of,
    lock_buyer_rows,
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
    _retried(lambda: _erase_once(contact_id, user))


def _erase_once(contact_id, user):
    with DB_PROXY.atomic():
        # The locks a correction takes, in its order (the queue's items, then the rabbits), so the two queue up.
        holding = list(HerdTracking.select().where(HerdTracking.holder_contact == contact_id))
        lock_buyer_rows(holding, [r.individual_id for r in holding])
        _count, paths = delete_buyer_contacts([contact_id], "radering", user, whole_items=True)
    remove_originals(paths)  # only after the commit: a row never names a removed file


ATTEMPTS = 3  # a busy queue: the next night tries again, and an erasure answers 409


def _retried(attempt):
    """`attempt` again while the queue changes under it (QueueChanged, rolled back before anything went)."""
    for _ in range(ATTEMPTS - 1):
        try:
            return attempt()
        except QueueChanged:
            pass
    return attempt()


def _delete_locked(rule, action):
    """
    Deletes the buyers that match `rule`, under the writers' locks in their order (the queue's items, the rabbits,
    then the buyers, as erase_buyer_contact takes them), with `rule` read again under them before any buyer or
    document goes. A resubmission that links a kept buyer again, an undo of its sale's void and a longer round all
    move purge_at under those locks, so the buyer stays; and the delete's ON DELETE SET NULL never waits on a sale
    that an undo holds while the undo waits on the buyer. An item linked to a sale or rabbit after the items were
    locked would be locked after the rabbit, against the queue's order, so the purge rolls back and starts again.
    """
    return _retried(lambda: _delete_once(rule, action))


def _delete_once(rule, action):
    with DB_PROXY.atomic():
        ids = [contact_id for (contact_id,) in BuyerContact.select(BuyerContact.id).where(rule).tuples()]
        holding = list(HerdTracking.select().where(HerdTracking.holder_contact.in_(ids)))
        lock_buyer_rows(holding, {row.individual_id for row in holding})
        still = BuyerContact.select(BuyerContact.id).where(BuyerContact.id.in_(ids) & rule).order_by(BuyerContact.id)
        count, paths = delete_buyer_contacts([contact_id for (contact_id,) in still.for_update().tuples()], action)
    remove_originals(paths)
    return count


def purge_expired(now):
    """Name and town five years after they were entered, or a buyer kept across Dra tillbaka after its round."""
    return _delete_locked(BuyerContact.purge_at <= now, "gallring_fem_ar")


def purge_dead(now):  # pylint: disable=unused-argument  # every rule takes the clock
    """Once the association learns the rabbit is dead, its buyers' names and towns go before the five years."""
    dead = (Individual.death_date.is_null(False)) | (fn.COALESCE(Individual.death_note, "") != "")
    held = (
        HerdTracking.select(HerdTracking.holder_contact)
        .join(Individual, on=(Individual.id == HerdTracking.individual))
        .where(HerdTracking.holder_contact.is_null(False) & dead)
        .distinct()
    )
    return _delete_locked(BuyerContact.id.in_(held), "gallring_dod")


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
