"""
Flask CLI for certificates.

Usage:
    flask certificates reissue-v1 [--run] [--limit N] [--number G1157-2432] [--visa-namn]

`reissue-v1` gives every v1 certificate (a digital number and no current v2 row) a v2 certificate in the current
design (stamboken #142). The new certificate is attested by whoever issued the original, not by whoever runs the
command (Jonas 2026-11-23): the name in the v1 PDF's IntygasAv field, matched to exactly one active account that may
issue the rabbit's certificate (access to its origin herd). Every other case stops that rabbit and leaves its v1
certificate as it is, with the reason in the summary: no v1 PDF, no name in it, no such account (the old app let a
buyer press "Uppdatera", so the name can be the buyer's), or several.

Without --run nothing is signed or written. With --run each rabbit is its own transaction, and the original v1 PDF is
copied to certifikat/v1/<number>.pdf before the new one overwrites <number>/certificate.pdf. A rabbit that already has
a current v2 row is not selected, so a run can be repeated. The summary names rabbits and herds, never people, unless
--visa-namn asks for the attesters of the herds where more than one person issued.
"""

from collections import Counter, defaultdict

import click
import pdfrw
import utils.data_access as da
import utils.database as db
import utils.s3 as s3
from flask.cli import AppGroup
from peewee import fn
from utils.cert_acess import download_certificate_s3
from utils.cert_service_v2 import generate_and_store, invalidate_caches
from utils.certificate_lifecycle import CertState
from utils.certificates_v2 import SigningUnavailableError

certificates_cli = AppGroup("certificates", help="Certificates.")

NO_PDF = "ingen v1-PDF"
NO_NAME = "inget namn under Intygas av i v1-PDF:en"
NO_ACCOUNT = "inget aktivt konto med namnet får utfärda för uppfödarbesättningen"
SEVERAL = "flera konton med namnet får utfärda för uppfödarbesättningen"


def normalised(name):
    return " ".join((name or "").split()).casefold()


def attester_in(pdf_bytes):
    """The IntygasAv field of a v1 certificate (utils/certificates.py FORM_KEYS), "" when absent or unreadable."""
    try:
        pages = pdfrw.PdfReader(fdata=pdf_bytes).pages
    except Exception:  # pylint: disable=broad-except  # pdfrw raises its own errors and plain ones on a bad file
        return ""
    for page in pages:
        for annotation in page.Annots or []:
            if annotation.T is not None and annotation.T.decode() == "IntygasAv":
                value = annotation.V
                return (value.decode() if hasattr(value, "decode") else str(value or "")).strip()
    return ""


def v1_rabbits(number=None):
    """Rabbits with a digital number and no current v2 row, oldest first."""
    current = db.DigitalCertificateV2.select().where(
        (db.DigitalCertificateV2.individual == db.Individual.id) & db.DigitalCertificateV2.is_current
    )
    query = db.Individual.select().where(
        db.Individual.digital_certificate.is_null(False), ~fn.EXISTS(current), db.not_voided()
    )
    if number:
        query = query.where(db.Individual.number == number)
    return list(query.order_by(db.Individual.id))


def decide(rabbit, accounts):
    """(account, reason, name, pdf): the account when the v1 attester resolves to exactly one account that may issue,
    else None and the reason; the name and the v1 PDF as read."""
    try:
        pdf = download_certificate_s3(rabbit.number)
    except Exception:  # pylint: disable=broad-except  # botocore's NoSuchKey and connection errors alike
        return None, NO_PDF, "", None
    name = attester_in(pdf)
    if not name:
        return None, NO_NAME, "", pdf
    issuers = [user for user in accounts.get(normalised(name), []) if user.can_issue_certificate(rabbit)]
    if not issuers:
        return None, NO_ACCOUNT, name, pdf
    if len(issuers) > 1:
        return None, SEVERAL, name, pdf
    return issuers[0], None, name, pdf


def reissue(rabbit, user, v1_pdf):
    """One rabbit in its own transaction; False when it got a current v2 row meanwhile."""
    with db.DATABASE.atomic():
        da.lock_individual_for_edit(rabbit.id)
        rabbit = db.Individual.get_by_id(rabbit.id)
        if rabbit.cert_state() != CertState.DIGITAL_NUMBER:
            return False
        # The original goes first: generate_and_store overwrites <number>/certificate.pdf, its only copy.
        s3.get_s3_client().put_object(file_name=f"certifikat/v1/{rabbit.number}.pdf", file_data=v1_pdf)
        generate_and_store(rabbit, user, rabbit.as_dict(), user.uuid, replaces_v1=True)
    invalidate_caches(rabbit)
    return True


@certificates_cli.command("reissue-v1")
@click.option("--run", is_flag=True, help="Utfärda och skriv. Utan flaggan skrivs ingenting.")
@click.option("--limit", type=int, default=None, help="Högst så många kaniner.")
@click.option("--number", default=None, help="Bara den här kaninen, t.ex. G1157-2432.")
@click.option("--visa-namn", is_flag=True, help="Visa intygarna i besättningar med flera intygare.")
def reissue_v1(run, limit, number, visa_namn):
    """Give the v1 certificates a v2 certificate attested by the original issuer (stamboken #142)."""
    accounts = defaultdict(list)
    for user in db.User.select().where(db.User.is_active):
        if normalised(user.fullname):
            accounts[normalised(user.fullname)].append(user)

    rabbits = v1_rabbits(number)[:limit] if limit else v1_rabbits(number)
    stopped, done, skipped = [], 0, 0
    attesters = defaultdict(set)  # origin herd -> names read, to list the herds with more than one
    for rabbit in rabbits:
        user, reason, name, pdf = decide(rabbit, accounts)
        herd = rabbit.origin_herd.herd if rabbit.origin_herd else "-"
        if name:
            attesters[herd].add(name)
        if reason:
            stopped.append((rabbit.number, herd, reason))
            continue
        if not run:
            done += 1
            continue
        try:
            if reissue(rabbit, user, pdf):
                done += 1
            else:
                skipped += 1
        except SigningUnavailableError as exc:
            raise click.ClickException(f"Signeringen är inte tillgänglig. {done} återutfärdade innan.") from exc
        except Exception as exc:  # pylint: disable=broad-except  # one rabbit's failure must not stop the rest
            stopped.append((rabbit.number, herd, f"fel vid utfärdandet: {exc.__class__.__name__}"))

    click.echo(f"{'Återutfärdade' if run else 'Skulle återutfärdas'}: {done}")
    if run:
        click.echo(f"Hoppade över (fick ett v2-intyg under körningen): {skipped}")
    click.echo(f"Stoppade, behåller v1-intyget: {len(stopped)}")
    for reason, count in Counter(reason for _, _, reason in stopped).most_common():
        click.echo(f"  {count} {reason}")
    for rabbit_number, herd, reason in stopped:
        click.echo(f"  {rabbit_number} (besättning {herd}): {reason}")
    several = {herd: names for herd, names in attesters.items() if len(names) > 1}
    if several:
        click.echo(f"Besättningar med flera intygare, kontrollera för hand: {len(several)}")
        for herd, names in sorted(several.items()):
            click.echo(f"  {herd}: {len(names)} intygare" + (f" ({', '.join(sorted(names))})" if visa_namn else ""))
