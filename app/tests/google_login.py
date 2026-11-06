"""Drive the two Google login routes with Google itself mocked out."""

from unittest import mock

import utils.data_access as da

ID_TOKEN = {
    "sub": "google-sub",
    "email": "medlem@gotlandskaninen.se",
    "email_verified": True,
    "hd": "gotlandskaninen.se",
    "name": "Medlem",
    "picture": "https://example.com/medlem.png",
}


def token_login(client, authenticate):
    """POST /api/auth/google (Next.js). `authenticate` stands in for da.authenticate_with_credentials."""
    with (
        mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value=ID_TOKEN),
        mock.patch.object(da, "authenticate_with_credentials", side_effect=authenticate),
    ):
        return client.post("/api/auth/google", json={"credential": "token"})


def redirect_login(client, authenticate, userinfo=None, idtoken=None, auto_validate=False, account=None):
    """GET /api/login/google as Google's OAuth redirect lands (legacy).

    `userinfo` and `idtoken` stand in for the profile fetches after login; `account`
    turns on auto-registration with those account details.
    """
    with (
        mock.patch("utils.external_auth.authorized", return_value=True),
        mock.patch("utils.external_auth.get_persistent", return_value="google-sub"),
        mock.patch.object(da, "authenticate_with_credentials", side_effect=authenticate),
        mock.patch("utils.external_auth.google_userinfo", side_effect=userinfo or (lambda: None)),
        mock.patch("utils.external_auth.google_idtoken", side_effect=idtoken or (lambda: None)),
        mock.patch("herdbook._should_auto_validate_users", return_value=auto_validate),
        mock.patch("utils.external_auth.get_autocreate", return_value=account is not None),
        mock.patch("utils.external_auth.get_account_details", return_value=account),
    ):
        return client.get("/api/login/google", headers={"Referer": "https://accounts.google.com/"})
