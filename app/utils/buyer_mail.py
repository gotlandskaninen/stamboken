"""
The mails to a buyer outside the association (ADR-0016, docs/mejl.md). utils.herd_tracking queues them with the
buyer, in the sale's transaction; the text and the certificate are read when the mail goes.

utils.herd_tracking imports this module, so it imports nothing that imports that one, except inside a function.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from peewee import fn

from utils import settings
from utils.database import (
    DB_PROXY,
    HOLDER_CHANGING_KINDS,
    MEMBERSHIP_OPTIN_FOR,
    BuyerContact,
    DigitalCertificateV2,
    HerdTracking,
    Individual,
    SaleProposal,
    YearlyHerdReport,
    ht_order_desc,
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


BUYER_ADDRESS_LOCK = 0x48424241  # "HBBA": buyers' addresses


def lock_buyer_addresses(addresses, *, erased_hash=None, proposal=False):
    """After the rabbits, take every address lock in ascending lock-id order, including on a multi-sale report."""
    keys = {(email or "").strip().lower() for email in addresses} - {""}
    if settings.mail.link_secret:
        keys = {address_hash(email) for email in keys}
    if erased_hash:
        keys.add(erased_hash)
    if not keys:
        return
    lock = "pg_advisory_xact_lock_shared" if proposal else "pg_advisory_xact_lock"
    DB_PROXY.execute_sql(
        f"SELECT {lock}(%s, id) FROM "
        "(SELECT DISTINCT hashtext(key) AS id FROM unnest(%s::text[]) AS a(key) ORDER BY id) AS locks",
        (BUYER_ADDRESS_LOCK, list(keys)),
    )


def queue_buyer_mails(contact, sale):
    """
    For a buyer just created with `sale` (its TRANSFER row) who gave an e-mail: kopare.information, and
    kopare.medlemskap with the yes to membership contact. One of each per buyer: a corrected sale keeps its
    buyer, and the dedupe_key holds if anything queues again. A buyer of several rabbits is one buyer per sale;
    the invitation then goes once per address, decided at the SMTP handoff.
    """
    if contact is None or not contact.email:  # None: a sale older than five years stores no buyer
        return
    if contact.email_review_pending:
        from utils.inbox import notify, queue_workers  # pylint: disable=import-outside-toplevel

        for manager in queue_workers(sale.herd.genebank_id, managers_only=True):
            notify(manager, "kopare_adresskontroll", None, individual=sale.individual_id)
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


def _rabbit_name(rabbit):
    from utils.herd_tracking import (  # pylint: disable=import-outside-toplevel
        HerdTrackingInvalid,
        reject_contact_details,
    )

    name = _one_line(rabbit.name)
    try:
        reject_contact_details(name, links=True)
    except HerdTrackingInvalid:
        return ""
    return name


def sv_date(day):
    """A date as Swedish text: "30 mars 2027"."""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _last_kept_date(purge_at):
    return sv_date(purge_at.astimezone(_STOCKHOLM).date() - timedelta(days=1))


def _membership_current(contact):
    at = contact.membership_optin_at
    return at is not None and at > datetime.now(timezone.utc) - MEMBERSHIP_OPTIN_FOR


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


def lock_certificate_holder(params):
    """In the caller's transaction, keep the holder stable through PDF fetch or SMTP handoff."""
    individual = params["individual_id"]
    lock_individuals([individual])
    holder = (
        HerdTracking.select(HerdTracking.holder_contact)
        .where(
            HerdTracking.individual == individual,
            HerdTracking.voided_at.is_null(True),
            HerdTracking.kind.in_(HOLDER_CHANGING_KINDS),
        )
        .order_by(*ht_order_desc())
        .limit(1)
        .scalar()
    )
    return holder == params["buyer_contact_id"]


@mail_kind("kopare.information", priority=1, category="T")
def _information_mail(params, attempt=1):
    """
    The buyer's notice (GDPR art. 14) with the erase link and the certificate; none once the buyer is erased. A
    certificate that cannot be fetched is tried again, and from the third attempt the notice goes without it.
    """
    contact = BuyerContact.get_or_none(BuyerContact.id == params["buyer_contact_id"])
    rabbit = Individual.get_or_none(Individual.id == params["individual_id"])
    if contact is None or rabbit is None or not contact.email or contact.email_review_pending:
        return None
    membership = _membership_current(contact)
    note = None
    try:
        with DB_PROXY.atomic():
            pdf = _certificate_pdf(rabbit) if lock_certificate_holder(params) else None
    except Exception:  # pylint: disable=broad-except  # S3, disk or PDF: the queue retries, then the notice matters more
        if attempt < ATTACHMENT_GIVE_UP:
            raise
        logger.exception("Certificate for mail to buyer %s unavailable; sent without it", contact.id)
        pdf, note = None, "skickat utan bilaga: intyget kunde inte hämtas"
    return {
        "buyer": _one_line(contact.name),
        "name": _rabbit_name(rabbit),
        "number": rabbit.number,
        "until": _last_kept_date(contact.purge_at),
        "address": bool(contact.postal_address),  # kept with the name since #111; an older buyer has only a town
        "token": link_token(ERASE_PURPOSE, contact.id),
        "consent": contact.contact_consent_at is not None,
        "membership": membership,
        "notice_only": contact.email_notice_only,  # no försäljningsbevis (#273): the e-mail only for this mail
        "certificate": pdf is not None,
        "sent_note": note,
        "attachments": [(f"genbanksintyg-{rabbit.number}.pdf", "application/pdf", pdf)] if pdf else [],
    }


@mail_kind("kopare.medlemskap", priority=1, category="T")
def _membership_mail(params):
    """The welcome the buyer said yes to; none once the yes or the buyer is gone, or the address has had one."""
    contact = BuyerContact.get_or_none(BuyerContact.id == params["buyer_contact_id"])
    rabbit = Individual.get_or_none(Individual.id == params["individual_id"])
    if contact is None or rabbit is None or not _membership_current(contact):
        return None
    return {"buyer": _one_line(contact.name), "rabbit": _rabbit_name(rabbit) or rabbit.number}


def _same_buyer(contact_id):
    """The linked contact and reviewed or unambiguous matches, also after an e-mail has been purged."""
    contact = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    if contact is None or contact.email_notice_only:  # its mail promises this sale's details only (#273)
        return {contact_id}
    email = (contact.email or "").strip().lower()
    key = address_hash(email) if email else contact.erased_email_hash
    if key is None:
        return {contact_id}
    same = BuyerContact.erased_email_hash == key
    if email:
        same |= fn.lower(fn.trim(BuyerContact.email)) == email
    eligible = BuyerContact.select(BuyerContact.id, BuyerContact.email).where(~BuyerContact.email_review_pending)
    ids = {row.id for row in eligible.where(same)}
    if not email:  # only the HMAC remains to compare with the addresses that are still held
        live = eligible.where(BuyerContact.email.is_null(False))
        ids.update(row.id for row in live if address_hash(row.email) == key)
    return ids | {contact_id}


def _pending_proposals(contact_ids):
    from utils.herd_tracking import _buyer_name_key  # pylint: disable=import-outside-toplevel

    # a buyer without a försäljningsbevis erases this sale only, never a pending one (#273)
    contacts = list(BuyerContact.select().where(BuyerContact.id.in_(contact_ids), ~BuyerContact.email_notice_only))
    addresses = {address_hash(c.email): c.email.strip().lower() for c in contacts if c.email}
    buyers = {
        (_buyer_name_key(c.name), address_hash(c.email) if c.email else c.erased_email_hash)
        for c in contacts
        if c.email or c.erased_email_hash
    }
    if not buyers:
        return []
    email = SaleProposal.buyer["email"]
    pending = SaleProposal.select().where(SaleProposal.state == "foreslagen", email.is_null(False))
    if all(key in addresses for _, key in buyers):
        pending = pending.where(fn.lower(fn.trim(email)).in_(list(addresses.values())))
    # An unreviewed proposal must match both the address and one of the buyer's established names.
    return [p for p in pending if (_buyer_name_key(p.buyer["name"]), address_hash(p.buyer["email"])) in buyers]


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
    # Imported here: the report and inbox modules import utils.herd_tracking, which imports this module.
    from utils import arsrapport, sale_proposal  # pylint: disable=import-outside-toplevel
    from utils.herd_tracking import (  # pylint: disable=import-outside-toplevel
        QUEUE_CHANGED,
        HerdTrackingConflict,
        buyer_items,
        delete_buyer_contacts,
    )
    from utils.inbox import notify, queue_workers  # pylint: disable=import-outside-toplevel
    from utils.inbox_purge import remove_originals  # pylint: disable=import-outside-toplevel

    def sales(ids):
        return list(HerdTracking.select().where(HerdTracking.holder_contact.in_(ids)))

    with DB_PROXY.atomic():
        # The locks a correction takes, in its order (the queue's items, then the rabbits), as
        # utils.buyer_contact.erase_buyer_contact: without them a correction that carries the buyer over to a new
        # row commits in between, and that row loses its buyer without the mark that one was removed.
        ids = _same_buyer(contact_id)
        proposals = _pending_proposals(ids)
        report_ids = {p.report_id for p in proposals}
        reports = YearlyHerdReport.select().where(YearlyHerdReport.id.in_(report_ids))
        for report in reports.order_by(YearlyHerdReport.round, YearlyHerdReport.herd):
            arsrapport.lock_report(report.round, report.herd)
        if report_ids:
            list(reports.order_by(YearlyHerdReport.id).for_update())
        holding = sales(ids)
        proposed_rabbits = {p.individual_id for p in proposals}
        # All reports before any items, then all rabbits in one pass, even across several reports and sales.
        items = arsrapport._lock_items(proposed_rabbits, kept=ids, reports=report_ids)  # pylint: disable=protected-access
        rabbits = {row.individual_id for row in holding} | proposed_rabbits
        lock_individuals(rabbits)
        linked = BuyerContact.get_or_none(BuyerContact.id == contact_id)
        if linked:
            lock_buyer_addresses([linked.email], erased_hash=linked.erased_email_hash)
        ids = _same_buyer(contact_id)  # again, under the locks: a correction may have put a new contact in
        holding = sales(ids)
        pending = _pending_proposals(ids)
        active = HerdTracking.select().where(
            HerdTracking.individual.in_(proposed_rabbits), HerdTracking.voided_at.is_null()
        )
        if (
            not {p.id for p in pending} <= {p.id for p in proposals}
            or not buyer_items([*holding, *active]) <= items
            or not {row.individual_id for row in holding} <= rabbits
        ):
            raise HerdTrackingConflict(QUEUE_CHANGED)
        for proposal in pending:
            sale_proposal.clear_buyer(proposal, "invandning")
        # Before the delete: afterwards the sales no longer point at the buyers. Only this objection tells the
        # genebank; a manager's erasure and the purges do not. A repeated link finds no sales and so no notice.
        for genebank_id, individual in sorted({(r.herd.genebank_id, r.individual_id) for r in holding if r.herd_id}):
            for manager in queue_workers(genebank_id, managers_only=True):
                notify(manager, "kopare_borttagen", None, individual=individual)
        count, paths = delete_buyer_contacts(sorted(ids), "invandning", whole_items=True)
    remove_originals(paths)  # after the commit, as utils.buyer_contact.erase_buyer_contact
    return "removed" if count else "already_removed"
