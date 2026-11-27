"""Fixture for arsrapport-lank.spec.ts, run inside the isolated Playwright API: the confirmation link in a herd's
newest receipt mail that has one (spec 5.11), as the member's mailbox would get it."""

import json
import os
import re
import sys


def main(herd_code):
    if not (
        os.getenv("FLASK_ENV") == "testing"
        and os.getenv("POSTGRES_DB") == "herdbook_test"
        and os.getenv("MAIL_MODE", "log") == "log"
        and os.getenv("DEMO_INSTANCE", "false").lower() == "false"
        and re.fullmatch(r"M92\d\d", herd_code)
    ):
        raise RuntimeError("Expected the isolated test-api with log-only mail and a link herd")
    from utils import arsrapport, mail  # noqa: F401  # arsrapport registers the receipt mails
    from utils.database import Herd, MailMessage, YearlyHerdReport, YearlyReportSubmission

    herd = Herd.get(Herd.herd == herd_code)
    submissions = (
        YearlyReportSubmission.select(YearlyReportSubmission.id)
        .join(YearlyHerdReport)
        .where(YearlyHerdReport.herd == herd.id)
    )
    receipts = MailMessage.select().where(
        MailMessage.kind.in_(("arsrapport.kvitto", "arsrapport.andrad")),
        MailMessage.ref_type == "yearly_report_submission",
        MailMessage.ref_id.in_(submissions),
    )
    for row in receipts.order_by(MailMessage.id.desc()):
        variables = mail.MAIL_KINDS[row.kind].build(row.params)
        if variables and variables.get("andringar"):
            variables.pop("attachments", None)
            subject, body = mail.render(row.kind, variables)
            return {"subject": subject, "fragment": re.search(r"/rapport/andringar(#\S+)$", body, re.M)[1]}
    return None


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:])))
