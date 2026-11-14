"""
Instance specific settings for the herdbook.
"""

import json
import logging
import os
from argparse import Namespace
from pathlib import Path

logging.info("Reading Environment")

postgres = Namespace()  # pylint: disable=C0103
s3 = Namespace()  # pylint: disable=C0103
certs = Namespace()  # pylint: disable=C0103
service = Namespace()  # pylint: disable=C0103
# Read configuration from environment variable

certs.private_key = Path(os.environ.get("PDF_SIGNING_KEY", "certs/key.pem"))
certs.ca = Path(os.environ.get("PDF_SIGNING_CA", "certs/ca.pem"))
# Trust roots for verifying uploaded certificates: the signing CA plus any
# earlier CAs (PDF_SIGNING_TRUST_CAS, comma-separated) so certificates issued
# before a key rotation still verify.
certs.trust_cas = [certs.ca] + [
    Path(p.strip()) for p in os.environ.get("PDF_SIGNING_TRUST_CAS", "").split(",") if p.strip()
]
certs.template = Path("template.pdf")
# The committed dev/test key: public by design, so production must never sign
# with it (see refuse_committed_signing_key).
certs.committed_key = Path(__file__).resolve().parent.parent / "certs" / "key.pem"
# Demo instances (api-test / herdbook_demo) stamp every v2 certificate with a
# red "DEMO – EJ GILTIGT INTYG" overlay. They must also never be given the
# production PDF_SIGNING_KEY — the defaults above (committed dev certs) apply.
certs.demo_watermark = os.environ.get("CERT_DEMO_WATERMARK", "false").lower() == "true"
certs.signing_enabled = os.environ.get("PDF_SIGNING_ENABLED", "true").lower() != "false"


def refuse_committed_signing_key():
    """Fail-safe at startup: a production instance that issues real certificates
    must not sign with the key that lives in this public repository. Demo
    instances (watermarked) and instances with signing disabled may use it."""
    if os.environ.get("FLASK_ENV") != "production" or certs.demo_watermark or not certs.signing_enabled:
        return
    key = certs.private_key
    same = False
    try:
        same = key.resolve() == certs.committed_key.resolve() or (
            key.is_file() and key.read_bytes() == certs.committed_key.read_bytes()
        )
    except OSError:
        same = False
    if same:
        raise RuntimeError(
            f"PDF_SIGNING_KEY={key} is the committed dev/test key from app/certs/. "
            "A production instance must sign with its own key (PDF_SIGNING_KEY=/config/pdf_signing_key.pem, "
            "PDF_SIGNING_CA=/config/pdf_signing_ca.pem), or set CERT_DEMO_WATERMARK=true / PDF_SIGNING_ENABLED=false."
        )


postgres.name = os.environ.get("POSTGRES_DB", "herdbook")
postgres.host = os.environ.get("POSTGRES_HOST", "herdbook-db")
postgres.port = os.environ.get("POSTGRES_PORT", "5432")
postgres.user = os.environ.get("POSTGRES_USER", "herdbook")
postgres.password = os.environ.get("POSTGRES_PASSWORD", "insecure")

service.host = os.environ.get("HERDBOOK_HOST", "https://127.0.0.1:8443")
service.logfolder = os.environ.get("HERDBOOK_LOGFOLDER", "./")
# The demo API (api-test): its logins are marked, and production refuses them.
service.demo_instance = os.environ.get("DEMO_INSTANCE", "false").lower() == "true"
# Originals of the intake queue (docs/inkorg.md). Never under UPLOAD_FOLDER: nginx serves all of that unauthenticated.
service.private_upload_folder = os.environ.get("PRIVATE_UPLOAD_FOLDER", "/app/skyddat")


def refuse_private_folder_under_uploads():
    """Fail-safe at startup: a private folder inside the upload folder would publish every original."""
    uploads = os.path.realpath(os.environ.get("UPLOAD_FOLDER", "/app/uppladdningar"))
    private = os.path.realpath(service.private_upload_folder)
    if os.path.commonpath([uploads, private]) in (uploads, private):
        raise RuntimeError(
            f"PRIVATE_UPLOAD_FOLDER={private} overlaps UPLOAD_FOLDER={uploads}, which nginx serves without login."
        )


def refuse_auto_validate_outside_demo():
    """Fail-safe at startup: auto-validation lets any domain Google account in,
    which is acceptable only on the demo, whose sessions production refuses."""
    if (
        os.environ.get("FLASK_ENV") == "production"
        and os.environ.get("AUTO_VALIDATE_USERS", "").lower() == "true"
        and not service.demo_instance
    ):
        raise RuntimeError(
            "AUTO_VALIDATE_USERS=true is only allowed on the demo API (DEMO_INSTANCE=true), "
            "whose logins production refuses."
        )


mail = Namespace()  # pylint: disable=C0103
# Outgoing mail (docs/mejl.md). The mode is the guard that keeps the demo from mailing members.
mail.mode = (os.environ.get("MAIL_MODE") or "log").strip().lower()
mail.allowlist = [entry.strip().lower() for entry in os.environ.get("MAIL_ALLOWLIST", "").split(",") if entry.strip()]
mail.smtp_host = os.environ.get("SMTP_HOST", "smtp-relay.gmail.com")
mail.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
mail.sender = os.environ.get("MAIL_FROM", "stamboken@gotlandskaninen.se")
# Its own secret per environment, not SECRET_KEY: link tokens, Message-IDs and address hashes.
mail.link_secret = os.environ.get("LINK_SECRET", "")


def refuse_unsafe_mail_settings():
    """Fail-safe at startup, like refuse_auto_validate_outside_demo: the demo never mails for real."""
    if mail.mode not in ("live", "allowlist", "log"):
        raise RuntimeError(f"MAIL_MODE={mail.mode!r} is not one of live, allowlist or log.")
    if mail.mode == "live" and service.demo_instance:
        raise RuntimeError("MAIL_MODE=live is refused on the demo API (DEMO_INSTANCE=true); use allowlist.")
    if mail.mode != "log" and not mail.link_secret:
        raise RuntimeError(f"MAIL_MODE={mail.mode} requires LINK_SECRET.")


gmail = Namespace()  # pylint: disable=C0103
# Reading the association's mailbox into the intake queue (docs/inkorg-gmail.md). Reading moves mail to the trash.
gmail.mode = (os.environ.get("INLASNING_GMAIL") or "off").strip().lower()
gmail.client_id = os.environ.get("GMAIL_CLIENT_ID", "")
gmail.client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
gmail.refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "")


def refuse_unsafe_gmail_settings():
    """Fail-safe at startup: the demo never reads the mailbox, and reading needs its credentials."""
    if gmail.mode not in ("on", "off"):
        raise RuntimeError(f"INLASNING_GMAIL={gmail.mode!r} is not on or off.")
    if gmail.mode == "off":
        return
    if service.demo_instance:
        raise RuntimeError("INLASNING_GMAIL=on is refused on the demo API (DEMO_INSTANCE=true): reading trashes mail.")
    if not (gmail.client_id and gmail.client_secret and gmail.refresh_token):
        raise RuntimeError("INLASNING_GMAIL=on requires GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN.")
    if not mail.link_secret:  # replies are tied to their question by the Message-ID's HMAC
        raise RuntimeError("INLASNING_GMAIL=on requires LINK_SECRET.")


interpretation = Namespace()  # pylint: disable=C0103
# The intake queue's image reading (docs/inkorg.md, "Tolkning"): av, the default, reads nothing.
interpretation.interpreter = (os.environ.get("INLASNING_TOLKARE") or "av").strip().lower()
interpretation.model = os.environ.get("INLASNING_MODELL") or "gemma4"
interpretation.ollama_url = (os.environ.get("OLLAMA_URL") or "http://ollama:11434").rstrip("/")

inbox = Namespace()  # pylint: disable=C0103
# The intake queue's retention (docs/inkorg.md, "Gallring"): the months an original of a certificate or a proof is
# kept after its item came in.
inbox.original_months = int(os.environ.get("INLASNING_ORIGINAL_MANADER") or 12)
if inbox.original_months < 1:
    raise RuntimeError(f"INLASNING_ORIGINAL_MANADER={inbox.original_months} is not a number of months, 1 or more.")

s3.bucket = os.environ.get("S3_BUCKET", "test")
s3.endpoint = os.environ.get("S3_ENDPOINT", None)
s3.region = os.environ.get("S3_REGION", "us-east-1")
s3.secret_key = os.environ.get("S3_SECRETKEY", "secretkeytest")
s3.access_key = os.environ.get("S3_ACCESSKEY", "accesskeytest")
s3.verify = json.loads(os.environ.get("S3_VERIFY", "True").lower())
s3.use_ssl = json.loads(os.environ.get("S3_USESSL", "True").lower())
s3.cert = None
s3.private_key = None
