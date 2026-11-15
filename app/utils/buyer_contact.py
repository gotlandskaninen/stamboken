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
    can_see_buyer,
    delete_buyer_contacts,
    is_manager_of,
    log_buyer_contact,
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


def erase_buyer_contact(contact_id, user):
    """
    DELETE /api/v2/buyer-contacts/<id>: every detail of the buyer goes, also name and town; the sale and its
    TRANSFER row stay. Admin, or a manager of the genebank of the row holding the buyer; anyone who may not see the
    buyer is told it does not exist.
    """
    contact = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    genebank_id = buyer_genebank(contact_id) if contact else None
    if contact is None or not (user.is_admin or (genebank_id is not None and can_see_buyer(user, genebank_id))):
        raise HerdTrackingNotFound("Köparen finns inte.")
    if not (user.is_admin or is_manager_of(user, genebank_id)):
        raise HerdTrackingForbidden("Bara genbanksansvarig eller administratör kan radera köparens uppgifter.")
    with DB_PROXY.atomic():
        _count, paths = delete_buyer_contacts([contact_id], "radering", user)
    remove_originals(paths)  # only after the commit: a row never names a removed file


def purge_expired(now):
    """Name and town five years after they were entered: the buyer goes."""
    with DB_PROXY.atomic():
        expired = BuyerContact.select(BuyerContact.id).where(BuyerContact.purge_at <= now)
        count, paths = delete_buyer_contacts([contact_id for (contact_id,) in expired.tuples()], "gallring_fem_ar")
    remove_originals(paths)
    return count


def purge_dead(now):  # pylint: disable=unused-argument  # every rule takes the clock
    """Once the association learns the rabbit is dead, its buyers' names and towns go before the five years."""
    dead = (Individual.death_date.is_null(False)) | (fn.COALESCE(Individual.death_note, "") != "")
    with DB_PROXY.atomic():
        held = (
            HerdTracking.select(HerdTracking.holder_contact)
            .join(Individual, on=(Individual.id == HerdTracking.individual))
            .where(HerdTracking.holder_contact.is_null(False) & dead)
            .distinct()
        )
        count, paths = delete_buyer_contacts([contact_id for (contact_id,) in held.tuples()], "gallring_dod")
    remove_originals(paths)
    return count


def _null_fields(where, changes, action):
    """
    Nulls `changes` on the buyers matching `where`, one audit_log row each naming the columns, and the mail queue
    forgets an e-mail address that went; returns how many.
    """
    with DB_PROXY.atomic():
        mailed = BuyerContact.select(BuyerContact.id).where(where & BuyerContact.email.is_null(False))
        mailed = {contact_id for (contact_id,) in mailed.tuples()}
        changed = list(
            BuyerContact.update(changes).where(where).returning(BuyerContact.id, BuyerContact.email).tuples()
        )
        for contact_id, email in changed:
            log_buyer_contact(contact_id, "UPDATE", action, fields=[field.name for field in changes])
            if email is None and contact_id in mailed:
                forget_recipient("buyer_contact", contact_id)
    return len(changed)


def purge_sold_on(now):  # pylint: disable=unused-argument  # every rule takes the clock
    """
    The contact consent once the rabbit has another holder: a later active TRANSFER or CORRECTION to another herd
    or another buyer. Address, e-mail and phone go with it; e-mail and phone stay while the membership yes does.
    """
    sale, later = HerdTracking, HerdTracking.alias()
    sold_on = (
        sale.select(sale.holder_contact)
        .join(later, on=(later.individual == sale.individual))
        .where(
            sale.holder_contact.is_null(False)
            & sale.voided_at.is_null(True)
            & later.voided_at.is_null(True)
            & later.kind.in_(("TRANSFER", "CORRECTION"))
            & (
                (later.herd != sale.herd)
                | later.holder_contact.is_null(True)
                | (later.holder_contact != sale.holder_contact)
            )
            & (
                (later.herd_tracking_date > sale.herd_tracking_date)
                | ((later.herd_tracking_date == sale.herd_tracking_date) & (later.id > sale.id))
            )
        )
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
    return _null_fields(BuyerContact.id.in_(sold_on) & kept, changes, "gallring_salld_vidare")


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
