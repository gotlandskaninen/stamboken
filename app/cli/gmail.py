"""
Flask CLI for the intake queue's Gmail reader (docs/inkorg-gmail.md).

Usage:
    flask gmail consent

`consent` is the one-time OAuth consent of an installed app: it prints the URL to open as the mailbox's
account, takes the address the browser ends up on (or just its code), and prints the refresh token to stdout,
the only place it ever goes. Run it with INLASNING_GMAIL=off and GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET set.
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import click
import requests
from flask.cli import AppGroup
from utils import settings
from utils.gmail import AUTH_URI, SCOPE, TOKEN_URI

gmail_cli = AppGroup("gmail", help="The intake queue's Gmail reader.")

# Google retired the copy-paste (out-of-band) redirect; a desktop client redirects to the loopback address,
# where nothing listens: the browser shows an error page, and its address holds the code.
REDIRECT_URI = "http://127.0.0.1:8765/"


@gmail_cli.command("consent")
def consent():
    """One-time consent for gmail.modify; prints the refresh token to stdout."""
    client_id, client_secret = settings.gmail.client_id, settings.gmail.client_secret
    if not (client_id and client_secret):
        raise click.ClickException("Sätt GMAIL_CLIENT_ID och GMAIL_CLIENT_SECRET först.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    click.echo("Öppna adressen nedan, logga in som brevlådans konto och godkänn:", err=True)
    click.echo(f"{AUTH_URI}?{urlencode(query)}", err=True)
    click.echo("Webbläsaren hamnar sedan på en sida som inte går att nå. Kopiera dess adress.", err=True)
    answer = click.prompt("Adressen (eller bara koden)", err=True).strip()
    code = parse_qs(urlparse(answer).query).get("code", [answer])[0]
    response = requests.post(
        TOKEN_URI,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=30,
    )
    token = response.json().get("refresh_token") if response.ok else None
    if not token:
        raise click.ClickException(f"Google gav ingen uppdateringstoken (HTTP {response.status_code}).")
    click.echo(token)
