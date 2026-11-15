"""
The mails to a buyer outside the association (ADR-0016, docs/mejl.md). utils.herd_tracking queues them with the
buyer, in the sale's transaction; the text and the certificate are read when the mail goes.

utils.herd_tracking imports this module, so it imports nothing that imports that one, except inside a function.
"""

import logging
import os
from zoneinfo import ZoneInfo

from peewee import fn

from utils import settings
from utils.database import (
    DB_PROXY,
    BuyerContact,
    DigitalCertificateV2,
    HerdTracking,
    Individual,
    MailMessage,
    lock_individuals,
)
from utils.mail import address_hash, enqueue_mail, link_token, mail_kind, verify_link

logger = logging.getLogger(__name__)

ERASE_PURPOSE = "kopare_invandning"  # link_token's purpose for the link that erases the buyer
ATTACHMENT_GIVE_UP = 3  # the attempt from which kopare.information goes without a certificate it cannot fetch
_STOCKHOLM = ZoneInfo("Europe/Stockholm")
_MONTHS = (
    "januari",
    "februari",
    "mars",
    "april",
    "maj",
    "juni",
    "juli",
    "augusti",
    "september",
    "oktober",
    "november",
    "december",
)


def queue_buyer_mails(contact, sale):
    """
    For a buyer just created with `sale` (its TRANSFER row) who gave an e-mail: kopare.information, and
    kopare.medlemskap with the yes to membership contact. One of each per buyer: a corrected sale keeps its
    buyer, and the dedupe_key holds if anything queues again. A buyer of several rabbits is one buyer per sale;
    the invitation then goes once per address, decided when it is sent (_membership_mail).
    """
    if not contact.email:
        return
    params = {"buyer_contact_id": contact.id, "individual_id": sale.individual_id}
    kinds = ("kopare.information", "kopare.medlemskap") if contact.membership_optin_at else ("kopare.information",)
    for kind in kinds:
        enqueue_mail(
            kind,
            "buyer_contact",
            contact.id,
            params,
            genebank=sale.herd.genebank_id,
            dedupe_key=f"{kind}:{contact.id}",
        )


def _one_line(value):
    """Free text from the seller goes into the mail on one line, so it cannot add lines of its own."""
    return " ".join((value or "").split())


def _swedish_date(moment):
    day = moment.astimezone(_STOCKHOLM)
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _certificate_pdf(rabbit):
    """
    The rabbit's digital certificate as GET /api/v2/certificates/<number> serves it, or None when it has none. A
    file that cannot be fetched raises: the queue tries again rather than send the mail without it.
    """
    # Imported here: cert_acess imports data_access, which imports utils.herd_tracking.
    from utils.cert_acess import (  # pylint: disable=import-outside-toplevel
        download_certificate_s3,
        download_certificate_v2,
    )

    cert = DigitalCertificateV2.get_or_none(
        (DigitalCertificateV2.individual == rabbit.id) & DigitalCertificateV2.is_current
    )
    if cert is None:
        return None if rabbit.digital_certificate is None else download_certificate_s3(rabbit.number)
    path = os.path.join("uppladdningar", cert.file_path)
    if not os.path.exists(path):
        return download_certificate_v2(cert.verification_token)
    with open(path, "rb") as pdf:
        return pdf.read()


@mail_kind("kopare.information", priority=1, category="T")
def _information_mail(params, attempt=1):
    """
    The buyer's notice (GDPR art. 14) with the erase link and the certificate; none once the buyer is erased. A
    certificate that cannot be fetched is tried again, and from the third attempt the notice goes without it.
    """
    contact = BuyerContact.get_or_none(BuyerContact.id == params["buyer_contact_id"])
    rabbit = Individual.get_or_none(Individual.id == params["individual_id"])
    if contact is None or rabbit is None:
        return None
    note = None
    try:
        pdf = _certificate_pdf(rabbit)
    except Exception:  # pylint: disable=broad-except  # S3, disk or PDF: the queue retries, then the notice matters more
        if attempt < ATTACHMENT_GIVE_UP:
            raise
        logger.exception("Certificate for mail to buyer %s unavailable; sent without it", contact.id)
        pdf, note = None, "skickat utan bilaga: intyget kunde inte hämtas"
    return {
        "buyer": _one_line(contact.name),
        "name": _one_line(rabbit.name),
        "number": rabbit.number,
        "until": _swedish_date(contact.purge_at),
        "token": link_token(ERASE_PURPOSE, contact.id),
        "consent": contact.contact_consent_at is not None,
        "membership": contact.membership_optin_at is not None,
        "certificate": pdf is not None,
        "sent_note": note,
        "attachments": [(f"genbanksintyg-{rabbit.number}.pdf", "application/pdf", pdf)] if pdf else [],
    }


@mail_kind("kopare.medlemskap", priority=1, category="T")
def _membership_mail(params):
    """The welcome the buyer said yes to; none once the yes or the buyer is gone, or the address has had one."""
    contact = BuyerContact.get_or_none(BuyerContact.id == params["buyer_contact_id"])
    rabbit = Individual.get_or_none(Individual.id == params["individual_id"])
    if contact is None or contact.membership_optin_at is None or rabbit is None:
        return None
    # Once per address, from the mails that have gone: each buyer holds an invitation of its own, so one buyer's
    # deletion never cancels the invitation of another with the same address.
    gone = (
        (MailMessage.kind == "kopare.medlemskap")
        & (MailMessage.status == "sent")
        & (MailMessage.address_hash == address_hash(contact.email))
    )
    if settings.mail.link_secret and MailMessage.select().where(gone).exists():
        return None
    return {"buyer": _one_line(contact.name), "rabbit": _one_line(rabbit.name) or rabbit.number}


def _same_buyer(contact_id):
    """
    The ids of the buyers with the address of buyer `contact_id`, that one included: a buyer of several rabbits
    is one contact per sale. A purge may have taken the linked contact's own e-mail (the rabbit was sold on)
    while a mail to it still holds the address's HMAC; the others are then found from that.
    """
    ids = {contact_id}
    contact = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    if contact is None:
        return ids
    email = (contact.email or "").strip().lower()
    if email:
        same = BuyerContact.select(BuyerContact.id).where(fn.lower(fn.trim(BuyerContact.email)) == email)
        return ids | {row.id for row in same}
    sent_to = (
        (MailMessage.recipient_kind == "buyer_contact")
        & (MailMessage.recipient_id == contact_id)
        & MailMessage.address_hash.is_null(False)
    )
    hashes = {row.address_hash for row in MailMessage.select(MailMessage.address_hash).where(sent_to)}
    if hashes and settings.mail.link_secret:
        others = BuyerContact.select(BuyerContact.id, BuyerContact.email).where(BuyerContact.email.is_null(False))
        ids |= {other.id for other in others if address_hash(other.email) in hashes}
    return ids


def erase_by_link(token):
    """
    POST /api/v2/kopare/ta-bort: the buyer objects through the link in kopare.information, and every detail goes
    as when a manager erases the buyer, with the action "invandning" and no user. "removed" or "already_removed"
    for a genuine link; None for any other token, decided before the database is read, so the answer never tells
    whether an id exists. A buyer of several rabbits has one contact per sale: every contact with the same
    address goes with the one in the link (_same_buyer). HerdTrackingConflict when the queue or the buyer's
    sales changed while the locks were taken: nothing is erased, and the buyer tries again.
    """
    contact_id = verify_link(ERASE_PURPOSE, token)
    if contact_id is None:
        return None
    # Imported here: both import utils.herd_tracking, which imports this module.
    from utils.herd_tracking import (  # pylint: disable=import-outside-toplevel
        QUEUE_CHANGED,
        HerdTrackingConflict,
        buyer_items,
        delete_buyer_contacts,
    )
    from utils.inbox_purge import remove_originals  # pylint: disable=import-outside-toplevel

    def sales(ids):
        return list(HerdTracking.select().where(HerdTracking.holder_contact.in_(ids)))

    with DB_PROXY.atomic():
        # The locks a correction takes, in its order (the queue's items, then the rabbits), as
        # utils.buyer_contact.erase_buyer_contact: without them a correction that carries the buyer over to a new
        # row commits in between, and that row loses its buyer without the mark that one was removed.
        holding = sales(_same_buyer(contact_id))
        items = buyer_items(holding, lock=True)
        rabbits = {row.individual_id for row in holding}
        lock_individuals(rabbits)
        ids = _same_buyer(contact_id)  # again, under the locks: a correction may have put a new contact in
        holding = sales(ids)
        if not buyer_items(holding) <= items or not {row.individual_id for row in holding} <= rabbits:
            raise HerdTrackingConflict(QUEUE_CHANGED)
        count, paths = delete_buyer_contacts(sorted(ids), "invandning", whole_items=True)
    remove_originals(paths)  # after the commit, as utils.buyer_contact.erase_buyer_contact
    return "removed" if count else "already_removed"
