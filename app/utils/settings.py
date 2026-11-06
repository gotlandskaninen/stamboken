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


s3.bucket = os.environ.get("S3_BUCKET", "test")
s3.endpoint = os.environ.get("S3_ENDPOINT", None)
s3.region = os.environ.get("S3_REGION", "us-east-1")
s3.secret_key = os.environ.get("S3_SECRETKEY", "secretkeytest")
s3.access_key = os.environ.get("S3_ACCESSKEY", "accesskeytest")
s3.verify = json.loads(os.environ.get("S3_VERIFY", "True").lower())
s3.use_ssl = json.loads(os.environ.get("S3_USESSL", "True").lower())
s3.cert = None
s3.private_key = None
