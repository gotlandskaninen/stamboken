"""
Flask CLI for accounts.

Usage:
    flask users add-role <konto> <roll>

`add-role` is the way back when the only admin has lost the Google account. It gives admin or matrikel_admin to an
account that can sign in: an active one with a Google login on the association's domain
(data_access.has_role_google_login), that is validated. <konto> is the account's e-mail address or username, and
exactly one account may answer to it.
"""

import click
from flask.cli import AppGroup
from utils import data_access as da
from utils.database import DB_PROXY, User

users_cli = AppGroup("users", help="Accounts.")


@users_cli.command("add-role")
@click.argument("konto")
@click.argument("roll", type=click.Choice(["admin", "matrikel_admin"]))
def add_role(konto, roll):
    """Give ROLL to KONTO, an active account with a Google login on the association's domain that is validated."""
    with DB_PROXY.atomic():
        # The account's row, as update_role and an unlink take it: the Google login cannot go meanwhile.
        # E-mail is not unique, and a username can be another account's e-mail: exactly one account answers.
        matches = list(User.select().where((User.email == konto) | (User.username == konto)).for_update())
        if not matches:
            raise click.ClickException(f"Inget konto med e-postadressen eller användarnamnet {konto}.")
        if len(matches) > 1:
            raise click.ClickException(f"{len(matches)} konton svarar på {konto}. Ange ett som bara ett konto har.")
        user = matches[0]
        if not user.is_active:
            raise click.ClickException("Kontot är inaktiverat.")
        if not user.validated:
            raise click.ClickException("Kontot är inte validerat (webbkursen).")
        if not da.has_role_google_login(user):
            raise click.ClickException("Kontot har ingen Google-inloggning med föreningens adress.")
        if user.has_role(roll):
            click.echo(f"Kontot har redan rollen {roll}.")
            return
        user.add_role(roll)
    da.auth_log.info("Role %s given from the command line to user id=%s", roll, user.id)
    click.echo(f"Kontot har fått rollen {roll}.")
