"""
Flask CLI for accounts.

Usage:
    flask users add-role <konto> <roll>

`add-role` is the way back when the only admin has lost the Google account. It gives admin or matrikel_admin to an
account that can sign in: an active one with a Google login on the association's domain
(data_access.has_role_google_login), that is validated. <konto> is the account's verified Google address
(google_email), never the contact address or username the holder can edit, and exactly one account may hold it.
"""

import click
from flask.cli import AppGroup
from peewee import fn
from utils import data_access as da
from utils.database import DB_PROXY, User

users_cli = AppGroup("users", help="Accounts.")


@users_cli.command("add-role")
@click.argument("konto")
@click.argument("roll", type=click.Choice(["admin", "matrikel_admin"]))
def add_role(konto, roll):
    """Give ROLL to the account whose verified Google address is KONTO: active, validated, on the domain."""
    with DB_PROXY.atomic():
        # The account's row, as update_role and an unlink take it: the Google login cannot go meanwhile.
        # Only the verified Google address: the holder can set the contact address to anyone's.
        matches = list(User.select().where(fn.LOWER(User.google_email) == konto.lower()).for_update())
        if not matches:
            raise click.ClickException(f"Inget konto har {konto} som verifierad Google-adress.")
        if len(matches) > 1:
            raise click.ClickException(f"{len(matches)} konton har {konto} som Google-adress. Rätta det först.")
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
