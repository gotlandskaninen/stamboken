"""
The buyer outside the association (ADR-0016): erasure on request or objection, and the nightly retention.

Registration, visibility and the deletion on a void live with the sale in utils.herd_tracking. Every rule takes
`now` and is idempotent; each erasure or purge writes one audit_log row without personal data.
"""

import logging
from datetime import timedelta

from peewee import Case

from utils.database import DB_PROXY, BuyerContact, HerdTracking
from utils.herd_tracking import (
    HerdTrackingForbidden,
    HerdTrackingNotFound,
    delete_buyer_contacts,
    is_manager_of,
    log_buyer_contact,
)
from utils.inbox_purge import remove_originals

logger = logging.getLogger("herdbook.buyer_contact")

MEMBERSHIP_OPTIN_FOR = timedelta(days=365)  # at most 12 months


def erase_buyer_contact(contact_id, user):
    """
    DELETE /api/v2/buyer-contacts/<id>: every detail of the buyer goes, also name and town; the sale and its
    TRANSFER row stay. Admin, or a manager of the genebank the rabbit is in.
    """
    contact = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    if contact is None:
        raise HerdTrackingNotFound("Köparen finns inte.")
    sale = HerdTracking.get_or_none(HerdTracking.holder_contact == contact_id)
    genebank_id = sale.individual.current_herd.genebank_id if sale else None
    if not (user.is_admin or (genebank_id is not None and is_manager_of(user, genebank_id))):
        raise HerdTrackingForbidden("Bara genbanksansvarig eller administratör kan radera köparens uppgifter.")
    with DB_PROXY.atomic():
        _count, paths = delete_buyer_contacts([contact_id], "radering", user, certificates=True)
    remove_originals(paths)  # only after the commit: a row never names a removed file


def purge_expired(now):
    """Name and town five years after they were entered: the buyer goes."""
    with DB_PROXY.atomic():
        expired = BuyerContact.select(BuyerContact.id).where(BuyerContact.purge_at <= now)
        count, paths = delete_buyer_contacts([contact_id for (contact_id,) in expired.tuples()], "gallring_fem_ar")
    remove_originals(paths)
    return count


def _null_fields(where, changes, action):
    """Nulls `changes` on the buyers matching `where`, one audit_log row each naming the columns; returns how many."""
    with DB_PROXY.atomic():
        changed = BuyerContact.update(changes).where(where).returning(BuyerContact.id).tuples()
        ids = [contact_id for (contact_id,) in changed]
        for contact_id in ids:
            log_buyer_contact(contact_id, "UPDATE", action, fields=[field.name for field in changes])
    return len(ids)


def purge_sold_on(now):  # pylint: disable=unused-argument  # every rule takes the clock
    """Address, e-mail and phone once the rabbit is sold on: a later active TRANSFER than the buyer's sale."""
    sale, later = HerdTracking, HerdTracking.alias()
    sold_on = (
        sale.select(sale.holder_contact)
        .join(later, on=(later.individual == sale.individual))
        .where(
            sale.holder_contact.is_null(False)
            & sale.voided_at.is_null(True)
            & later.voided_at.is_null(True)
            & (later.kind == "TRANSFER")
            & (
                (later.herd_tracking_date > sale.herd_tracking_date)
                | ((later.herd_tracking_date == sale.herd_tracking_date) & (later.id > sale.id))
            )
        )
    )
    kept = (
        BuyerContact.postal_address.is_null(False)
        | BuyerContact.email.is_null(False)
        | BuyerContact.phone.is_null(False)
        | BuyerContact.contact_consent_at.is_null(False)
    )
    changes = {
        BuyerContact.postal_address: None,
        BuyerContact.email: None,
        BuyerContact.phone: None,
        BuyerContact.contact_consent_at: None,
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


RULES = (purge_membership_optin, purge_sold_on, purge_expired)


def run(now):
    """The nightly buyer purge: every rule on its own, so one failing does not skip the others."""
    for rule in RULES:
        try:
            logger.info("Buyer purge %s: %s", rule.__name__, rule(now))
        except Exception:  # pylint: disable=broad-except
            logger.exception("Buyer purge %s failed", rule.__name__)
