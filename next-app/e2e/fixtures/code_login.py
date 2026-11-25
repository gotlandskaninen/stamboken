"""Fixture for public-code-login.spec.ts, run inside the isolated Playwright API."""

import json
import os
import re
import sys


def main(action, email):
    if not (
        os.getenv("FLASK_ENV") == "testing"
        and os.getenv("POSTGRES_DB") == "herdbook_test"
        and os.getenv("POSTGRES_HOST") == "localhost"
        and os.getenv("MAIL_MODE", "log") == "log"
        and os.getenv("DEMO_INSTANCE", "false").lower() == "false"
        and os.getenv("KODINLOGGNING", "").lower() == "true"
        and os.getenv("SJALVSKAPAT_KONTO_PROD", "").lower() == "true"
        and re.fullmatch(r"pw-code-[a-f0-9]{32}@example\.org", email)
    ):
        raise RuntimeError("Expected isolated test-api with log-only mail and both login flags enabled")
    from utils import login_code, mail  # login_code registers the mail kind and recipient
    from utils.database import DB_PROXY, Genebank, Herd, LoginCode, MailMessage, Member, Membership

    login_code.refuse_unsafe()
    if action == "seed":
        with DB_PROXY.atomic():
            membership = Membership.create()
            Member.create(
                membership=membership, role="huvudmedlem", first_name="Kodtest", last_name="Mobil", email=email
            )
            herd = Herd.create(
                membership=membership,
                genebank=Genebank.get(Genebank.name == "Gotlandskanin"),
                herd=f"G{7000000 + membership.id}",
                is_active=True,
            )
        return herd.herd
    if action == "mail":
        member = Member.get(Member.email == email, Member.user.is_null(True))
        row = LoginCode.get_or_none(LoginCode.member == member, LoginCode.purpose == "login")
        if row is None:
            return None
        queued = MailMessage.get(
            MailMessage.kind == "konto.kod",
            MailMessage.recipient_kind == "login_code",
            MailMessage.recipient_id == row.id,
        )
        if mail.RECIPIENT_KINDS["login_code"](row.id).address != email:
            raise RuntimeError("Expected the queued mail for this fixture")
        _, body = mail.render(queued.kind, mail.MAIL_KINDS[queued.kind].build(queued.params))
        return {
            "digits": re.search(r"^\d{4} \d{4}$", body, re.M)[0],
            "fragment": re.search(r"/auth/kod(#\S+)$", body, re.M)[1],
        }
    raise ValueError("Unknown fixture operation")


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:])))
