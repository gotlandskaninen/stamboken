"""
The mails to a buyer outside the association (ADR-0016, docs/mejl.md). utils.herd_tracking queues them with the
buyer, in the sale's transaction; the text and the certificate are read when the mail goes.

utils.herd_tracking imports this module, so it imports nothing that imports that one, except inside a function.
"""

import os
from zoneinfo import ZoneInfo

from utils.database import BuyerContact, DigitalCertificateV2, Individual
from utils.mail import enqueue_mail, link_token, mail_kind

ERASE_PURPOSE = "kopare_invandning"  # link_token's purpose for the link that erases the buyer
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
    kopare.medlemskap with the yes to membership contact. Once each per buyer: a corrected sale keeps its buyer,
    and the dedupe_key holds if anything queues again.
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
def _information_mail(params):
    """The buyer's notice (GDPR art. 14) with the erase link and the certificate; none once the buyer is erased."""
    contact = BuyerContact.get_or_none(BuyerContact.id == params["buyer_contact_id"])
    rabbit = Individual.get_or_none(Individual.id == params["individual_id"])
    if contact is None or rabbit is None:
        return None
    pdf = _certificate_pdf(rabbit)
    return {
        "buyer": contact.name,
        "name": rabbit.name,
        "number": rabbit.number,
        "until": _swedish_date(contact.purge_at),
        "token": link_token(ERASE_PURPOSE, contact.id),
        "certificate": pdf is not None,
        "attachments": [(f"genbanksintyg-{rabbit.number}.pdf", "application/pdf", pdf)] if pdf else [],
    }


@mail_kind("kopare.medlemskap", priority=1, category="T")
def _membership_mail(params):
    """The welcome the buyer said yes to; none once the yes or the buyer is gone."""
    contact = BuyerContact.get_or_none(BuyerContact.id == params["buyer_contact_id"])
    rabbit = Individual.get_or_none(Individual.id == params["individual_id"])
    if contact is None or contact.membership_optin_at is None or rabbit is None:
        return None
    return {"buyer": contact.name, "rabbit": rabbit.name or rabbit.number}
