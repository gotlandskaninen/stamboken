"""
Flask CLI for certificates.

Usage:
    flask certificates reissue-v1 [--run] [--limit N] [--number G1157-2432] [--visa-namn]

`reissue-v1` gives every v1 certificate (a digital number and no current v2 row) a v2 certificate in the current
design (stamboken #142). The new certificate is attested by whoever issued the original, not by whoever runs the
command (Jonas 2026-11-23). The v1 PDF at <number>/certificate.pdf is read field by field (utils/certificates.py
FORM_KEYS), and a rabbit is reissued only when all of these hold; otherwise it keeps its v1 certificate and the
summary says why:
- the PDF's Nummer is the rabbit's digital certificate number (the file belongs to this certificate);
- exactly one account, active or not, has the IntygasAv name, and it is active and may issue for the origin herd (the
  old app let a buyer press "Uppdatera", so the name can be the buyer's);
- IntygasNummer, the herd the rabbit was in when the v1 certificate was made, is filled in and is the origin herd;
- every other field equals what the certificate would say today, so nothing corrected since is put under the
  original attester's name.

Without --run nothing is signed or stored (the S3 client still sends its usual CreateBucket). With --run each rabbit
is its own transaction under the rabbit and number locks: the v1 PDF is copied to the data volume as
uppladdningar/certifikat/v1/<certificate number>.pdf and the v2 certificate is written next to the other v2 files.
S3 is only read (stamboken-drift #69, step A), so the v1 file stays where it is and a failed attempt can be run
again. A rabbit that has a current v2 row is not selected. The summary names rabbits, herds and fields, never people,
unless --visa-namn asks for the attesters of the herds where more than one person issued.
"""

import os
from collections import Counter, defaultdict

import click
import pdfrw
import utils.data_access as da
import utils.database as db
import utils.number_assets as number_assets
from botocore.exceptions import BotoCoreError, ClientError
from flask.cli import AppGroup
from peewee import SQL, fn
from utils.cert_acess import download_certificate_s3, get_certificate_data
from utils.cert_service_v2 import generate_and_store, invalidate_caches, sync_directories
from utils.certificate_lifecycle import CertState
from utils.certificates import FORM_KEYS
from utils.certificates_v2 import SigningUnavailableError

certificates_cli = AppGroup("certificates", help="Certificates.")

STATE = "intygsläget tillåter inte återutfärdande (t.ex. både pappers- och digitalt nummer)"
NO_PDF = "ingen v1-PDF"
UNREADABLE = "v1-PDF:en går inte att läsa"
OTHER_CERTIFICATE = "v1-PDF:en har ett annat intygsnummer"
NO_NAME = "inget namn under Intygas av"
SEVERAL = "flera konton har namnet"
NO_ACCOUNT = "inget konto har namnet"
INACTIVE = "kontot med namnet är inaktivt"
NO_RIGHT = "kontot med namnet får inte utfärda för uppfödarbesättningen"
OTHER_HERD = "v1-intyget utfärdades i en annan besättning än uppfödarens"
CHANGED = "uppgifterna har ändrats sedan v1-intyget"
NUMBER_CHANGED = "bara numret har ändrats sedan v1-intyget (kaninens eller en förälders)"
UNPROVEN = "en anfaders nummer har ändrats, utan belägg i audit-loggen för att det är samma kanin"
FAILED = "fel vid utfärdandet"

# Fields that are not facts about the rabbit: who, where and when it was attested, and the number checked on its own.
NOT_COMPARED = {"", "fullname", "herd", "issue_date", "digital_certificate"}
# A renumbering (a new number, litters renumbered, a corrected birth year or origin herd) is a correction the genebank
# managers may make (Jonas 2026-11-28): reported apart, and with --tillat-nytt-nummer reissued under today's number.
NUMBER_FIELDS = {field for field, key in FORM_KEYS.items() if key.endswith(("genebank_number", "genebank_aki"))}
# Each number on the v1 form: its two fields and how to reach that rabbit from the one reissued.
NUMBERS = {
    "": ("IdGenbanksNummer", "IdÅrKullIndivid", ()),
    "F": ("FarGenbanksNummer", "FarÅrKullIndivid", ("father",)),
    "M": ("MorGenbanksNummer", "MorÅrKullIndivid", ("mother",)),
    "FF": ("FarfarGenbanksNummer", "FarfarÅrKullInvidid", ("father", "father")),
    "FM": ("FarmorGenbanksNummer", "FarmorÅrKullInvidid", ("father", "mother")),
    "MF": ("MorfarGenbanksNummer", "MorfarÅrKullIndivid", ("mother", "father")),
    "MM": ("MormorGenbanksNummer", "MormorÅrKullIndivid", ("mother", "mother")),
}
# Printed on the v2 certificate but never on v1: left empty unless --ta-med-nya-falt (Jonas has not decided).
NOT_ON_V1 = ("foot_ring", "microchip", "rex")


class Stop(Exception):
    """The rabbit keeps its v1 certificate, for `reason` (and `fields`, when its data changed)."""

    def __init__(self, reason, fields=()):
        super().__init__(reason)
        self.reason, self.fields = reason, tuple(fields)


def normalised(value):
    """As the v1 form held it (CertificateGenerator._encode_pdf_string writes "" for any falsy value), compared
    without case and runs of whitespace."""
    return " ".join(str(value or "").split()).casefold()


def v1_fields(pdf_bytes):
    """The v1 form's fields as {name: value}; raises Stop when the file cannot be read."""
    try:
        fields = {}
        for page in pdfrw.PdfReader(fdata=pdf_bytes).pages:
            for annotation in page.Annots or []:
                value = annotation.V
                if annotation.T is not None and (value is None or isinstance(value, pdfrw.objects.PdfString)):
                    # Text fields only: the signature field endesive adds holds a dictionary.
                    fields[annotation.T.decode()] = value.decode() if value is not None else ""
        return fields
    except Exception as exc:  # pylint: disable=broad-except  # pdfrw's own errors, and bad UTF-16 when decoding
        raise Stop(UNREADABLE) from exc


def v1_pdf(rabbit):
    try:
        return download_certificate_s3(rabbit.number)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            raise Stop(NO_PDF) from exc
        raise  # access or connection: the whole run stops rather than report every rabbit as missing


def accounts_named(name):
    """Every account, active or not, whose name normalises to `name`: read anew for each rabbit."""
    return [user for user in db.User.select() if normalised(user.fullname) == name]


def attester(rabbit, fields):
    """The one account that may attest the new certificate, or Stop."""
    name = normalised(fields.get("IntygasAv"))
    if not name:
        raise Stop(NO_NAME)
    accounts = accounts_named(name)
    if len(accounts) > 1:
        raise Stop(SEVERAL)
    if not accounts:
        raise Stop(NO_ACCOUNT)
    (user,) = accounts
    if not user.is_active:
        raise Stop(INACTIVE)
    if not user.can_issue_certificate(rabbit):
        raise Stop(NO_RIGHT)
    if normalised(fields.get("IntygasNummer")) != normalised(rabbit.origin_herd.herd):  # empty proves nothing either
        raise Stop(OTHER_HERD)
    return user


def check(rabbit, pdf, allow_number=False):
    """The account to attest `rabbit`'s v2 certificate, or Stop. Reads the database and the PDF, writes nothing."""
    if rabbit.cert_state() != CertState.DIGITAL_NUMBER:
        raise Stop(STATE)
    fields = v1_fields(pdf)
    if normalised(fields.get("Nummer")) != normalised(rabbit.digital_certificate):
        raise Stop(OTHER_CERTIFICATE)
    user = attester(rabbit, fields)
    today = get_certificate_data(rabbit.as_dict(), user.uuid)
    changed = sorted(
        field
        for field, key in FORM_KEYS.items()
        if key not in NOT_COMPARED and normalised(fields.get(field)) != normalised(today.get(key))
    )
    if changed and not set(changed) <= NUMBER_FIELDS:
        raise Stop(CHANGED, changed)
    if changed and not all(renumbered(rabbit, fields, today, changed)):
        raise Stop(UNPROVEN, changed)
    if changed and not allow_number:
        raise Stop(NUMBER_CHANGED, changed)
    return user


def renumbered(rabbit, fields, today, changed):
    """
    For each number that differs from the v1 form: whether it is provably the same rabbit under a new number. The
    reissued rabbit is (its PDF carries its certificate number). An ancestor is only when today's certificate prints
    that ancestor's number, and the audit log shows that it, and no other rabbit, ever held the v1 number: a littermate
    put in as parent, a number handed on to another rabbit, or an ancestor the attester can no longer see is not.
    """
    for herd_field, aki_field, path in NUMBERS.values():
        if herd_field not in changed and aki_field not in changed:
            continue
        if not path:
            yield True
            continue
        ancestor = rabbit
        for parent in path:
            ancestor = getattr(ancestor.breeding, parent, None) if ancestor and ancestor.breeding else None
        printed = f"{today.get(FORM_KEYS[herd_field]) or ''}-{today.get(FORM_KEYS[aki_field]) or ''}"
        if ancestor is None or printed != ancestor.number:
            yield False
            continue
        old = f"{fields.get(herd_field, '').strip()}-{fields.get(aki_field, '').strip()}"
        holders = {
            row.record_id
            for row in db.AuditLog.select(db.AuditLog.record_id).where(
                (db.AuditLog.table_name == "individual")
                & SQL("(old_data->>'number' = %s OR new_data->>'number' = %s)", (old, old))
            )
        }
        held_now = db.Individual.select().where(db.Individual.number == old, db.Individual.id != ancestor.id).exists()
        yield holders == {str(ancestor.id)} and not held_now


ARCHIVE = os.path.join("uppladdningar", "certifikat", "v1")
ARCHIVED_OTHER = "arkivet har redan en annan v1-fil för intygsnumret"


def archive(rabbit, pdf):
    """Keep the v1 original on the data volume, once, under its certificate number, which never moves; synced before
    the v2 row commits, also when an earlier attempt left it unsynced."""
    path = os.path.join(ARCHIVE, f"{rabbit.digital_certificate}.pdf")
    if os.path.exists(path):
        with open(path, "rb") as kept:
            if kept.read() != pdf:
                raise Stop(ARCHIVED_OTHER)
    else:
        os.makedirs(ARCHIVE, exist_ok=True)
        # Complete or not at all: a half-written file under the final name would stop every later run.
        temporary = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temporary, "wb") as copy:
                copy.write(pdf)
                copy.flush()
                os.fsync(copy.fileno())
            os.link(temporary, path)  # never over an original already archived
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    sync_directories(ARCHIVE)  # the link and any directory made for it outlast a crash after the v2 row commits


def reissue(rabbit, allow_number=False, new_fields=False):
    """Check, archive and reissue one rabbit in its own transaction under its row and number locks, or Stop."""
    with db.DATABASE.atomic():
        # One snapshot for the check and the render: a grandparent changed meanwhile in another litter would otherwise
        # be signed unchecked. A conflicting write fails the rabbit, and a rerun checks it again.
        db.DATABASE.execute_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if not da.lock_individual_for_edit(rabbit.id):
            raise Stop(STATE)
        rabbit = db.Individual.get_by_id(rabbit.id)
        number_assets.lock_number(rabbit.number, xact=True)  # a renumber moves the v1 file in S3 under this lock
        pdf = v1_pdf(rabbit)
        user = check(rabbit, pdf, allow_number)
        archive(rabbit, pdf)
        blank = () if new_fields else NOT_ON_V1
        generate_and_store(rabbit, user, rabbit.as_dict(), user.uuid, replaces_v1=True, blank=blank)
    invalidate_caches(rabbit)


@certificates_cli.command("reissue-v1")
@click.option("--run", is_flag=True, help="Utfärda och skriv. Utan flaggan skrivs ingenting.")
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Återutfärda högst så många kaniner.")
@click.option("--number", default=None, help="Bara den här kaninen, t.ex. G1157-2432.")
@click.option("--visa-namn", is_flag=True, help="Visa intygarna i besättningar med flera intygare.")
@click.option(
    "--tillat-nytt-nummer", is_flag=True, help="Återutfärda också när bara numret har ändrats sedan v1-intyget."
)
@click.option("--ta-med-nya-falt", is_flag=True, help="Skriv ut benring, chip och päls, som inte stod på v1-intyget.")
def reissue_v1(run, limit, number, visa_namn, tillat_nytt_nummer, ta_med_nya_falt):
    """Give the v1 certificates a v2 certificate attested by the original issuer (stamboken #142)."""
    current = db.DigitalCertificateV2.select().where(
        (db.DigitalCertificateV2.individual == db.Individual.id) & db.DigitalCertificateV2.is_current
    )
    query = db.Individual.select().where(
        db.Individual.digital_certificate.is_null(False), ~fn.EXISTS(current), db.not_voided()
    )
    if number:
        query = query.where(db.Individual.number == number)

    done, stopped, fields_changed = 0, [], Counter()
    attesters = defaultdict(set)  # origin herd -> names read, to list the herds with more than one
    for rabbit in query.order_by(db.Individual.id):
        if limit is not None and done >= limit:
            break
        herd = rabbit.origin_herd.herd if rabbit.origin_herd else "-"
        try:
            if run:
                try:
                    reissue(rabbit, tillat_nytt_nummer, ta_med_nya_falt)
                except (Stop, SigningUnavailableError, ClientError, BotoCoreError):
                    raise
                except Exception as exc:  # pylint: disable=broad-except  # one rabbit's failure must not stop the rest
                    raise Stop(f"{FAILED}: {exc.__class__.__name__}") from exc
            else:
                pdf = v1_pdf(rabbit)
                try:
                    attesters[herd].add(normalised(v1_fields(pdf).get("IntygasAv")))
                except Stop:
                    pass
                check(rabbit, pdf, tillat_nytt_nummer)
            done += 1
        except Stop as stop:
            stopped.append((rabbit.number, herd, stop.reason))
            fields_changed.update((stop.reason, field) for field in stop.fields)
        except SigningUnavailableError as exc:
            raise click.ClickException(f"Signeringen är inte tillgänglig. {done} återutfärdade innan.") from exc
        except (ClientError, BotoCoreError) as exc:
            raise click.ClickException(f"S3 svarar inte som väntat: {exc}. {done} klara innan.") from exc

    click.echo(f"{'Återutfärdade' if run else 'Skulle återutfärdas'}: {done}")
    click.echo(f"Stoppade, behåller v1-intyget: {len(stopped)}")
    for reason, count in Counter(reason for _, _, reason in stopped).most_common():
        click.echo(f"  {count} {reason}")
        for (stopped_for, field), times in fields_changed.most_common():
            if stopped_for == reason:
                click.echo(f"    ändrat fält {field}: {times}")
    for rabbit_number, herd, reason in stopped:
        click.echo(f"  {rabbit_number} (besättning {herd}): {reason}")
    several = {herd: names_read - {""} for herd, names_read in attesters.items() if len(names_read - {""}) > 1}
    if several:
        click.echo(f"Besättningar med flera intygare, kontrollera för hand: {len(several)}")
        for herd, names_read in sorted(several.items()):
            shown = f" ({', '.join(sorted(names_read))})" if visa_namn else ""
            click.echo(f"  {herd}: {len(names_read)} intygare{shown}")
