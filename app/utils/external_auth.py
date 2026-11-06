#!/usr/bin/env python3
"""
Provides helper function needed for external authentication.
"""

import base64
import configparser
import json
import logging
import os

import flask_dance.contrib.google
import google.auth.transport.requests
from google.oauth2.service_account import Credentials

# Note: OAuth should now work with HTTPS proxy headers from Nginx
# If needed, uncomment the line below for local development:
# os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

CONFIGFILE = os.environ.get("AUTHCONFIGFILE", "/config/auth.ini")

_active: list[str] = []  # pylint: disable = invalid-name
_autocreate: list[str] = []  # pylint: disable = invalid-name
_config: dict = {}


def available_methods():
    """
    Returns available (configured) external authentication methods.
    The returned value is a list or tuple of method names.
    """
    return _active


def setup(app):
    """
    Setup method for external authentications. Reads CONFIGFILE and sets up
    configured authentication methods.
    """

    if not os.path.exists(CONFIGFILE):
        return

    config = configparser.ConfigParser()
    config.read(CONFIGFILE)

    for engine in config.sections():
        if config.getboolean(engine, "autocreate", fallback=False):
            _autocreate.append(engine)

        if engine == "google":
            setup_google(app, config)


def setup_google(app, config):
    """
    Setup google authentication.
    """

    hdparam = {}
    scopes = [
        "openid",
    ]

    if config["google"].get("autocreate", None):
        scopes.append("https://www.googleapis.com/auth/userinfo.profile")
        scopes.append("https://www.googleapis.com/auth/userinfo.email")

    if config["google"].get("domain", None):
        hdparam["hosted_domain"] = config["google"]["domain"]
        _config["googledomain"] = config["google"]["domain"]

    if config["google"].get("herdattribute", None):
        _config["googleherd"] = config["google"]["herdattribute"]

    if config["google"].get("credentialsfile", None):
        _config["googlecreds"] = config["google"]["credentialsfile"]

    if config["google"].get("lookupuser", None):
        _config["googlelookup"] = config["google"]["lookupuser"]

    danceengine = flask_dance.contrib.google
    blueprint = danceengine.make_google_blueprint(
        client_id=config["google"]["key"],
        client_secret=config["google"]["secret"],
        login_url="",
        redirect_url="/api/login/google",
        scope=scopes,
        **hdparam,
    )

    app.register_blueprint(blueprint, url_prefix="/api/login/google/back")
    _active.append("google")


def google_idtoken():
    """
    Extracts the idtoken from flask-dance and returns the payload.
    We rely on flask-dance for verifying the signature.
    """
    if not flask_dance.contrib.google.google.token:
        return None

    t = flask_dance.contrib.google.google.token["id_token"]
    return json.loads(
        base64.decodebytes(
            bytes(
                t.split(".")[1],
                "ASCII",
            )
            + b"=="  # Add padding, extra padding is harmless, missing blows up
        )
    )


def google_userinfo():
    """
    Fetch Google profile data (picture, name, email) via the userinfo endpoint.
    Uses flask-dance's authenticated OAuth session.
    Returns dict with picture/name/email or None if not available.
    """
    google = flask_dance.contrib.google.google
    if not google.authorized:
        return None

    try:
        resp = google.get("https://www.googleapis.com/oauth2/v2/userinfo")
        if resp.ok:
            return resp.json()
    except Exception as e:
        logging.warning(f"Failed to fetch Google userinfo: {e}")

    return None


def google_authorized():
    """
    Returns whatever we have authenticated/authorized with google.
    """

    idtoken = google_idtoken()
    if not idtoken:
        return False

    if "googledomain" in _config:
        if "hd" not in idtoken or idtoken["hd"] != _config["googledomain"]:
            return None

    return flask_dance.contrib.google.google.authorized


def google_persistent():
    """
    Return the persistent identifier for google.
    """

    idtoken = google_idtoken()

    if not idtoken:
        return None

    return idtoken["sub"]


def google_verified_email():
    """
    Return the Google account's address only when Google marks it verified,
    else None. This, not the self-editable User.email, is the identity.
    """

    idtoken = google_idtoken()

    if not idtoken or not idtoken.get("email_verified", False):
        return None

    return idtoken.get("email")


def google_details():
    """
    Return the e-mail
    """

    idtoken = google_idtoken()

    if not idtoken:
        return None

    # Only care about verified addresses
    if not idtoken.get("email_verified", False):
        return None

    out_token = {}

    if "email" in idtoken:
        out_token["email"] = idtoken["email"]

    if "googledomain" in _config:
        # Do we have an attribute specified for herd?
        userinfo = flask_dance.contrib.google.google.get(
            "https://admin.googleapis.com/admin/directory/v1/users/"
            + "{}?projection=full&viewType=domain_public".format(idtoken["sub"])
        )

        if userinfo.json() and "name" in userinfo.json() and "fullName" in userinfo.json()["name"]:
            out_token["fullname"] = userinfo.json()["name"]["fullName"]

        oneatt = False
        for attr in (
            "googlecreds",
            "googleherd",
            "googlelookup",
            "googlelookup",
        ):
            if attr in _config:
                oneatt = True

        notall = False

        if oneatt:
            for attr in (
                "googlecreds",
                "googleherd",
                "googlelookup",
            ):
                if attr not in _config:
                    logging.warning(
                        "One of herd attributes "
                        + "specified but not enough (must specify all "
                        + "of herdattribute, credentialsfile "
                        + "and lookupuser)."
                    )
                    notall = True

        if not notall:
            # Get credentials for an admin account through the service account
            cpath = "/config/{}".format(_config["googlecreds"])
            admincreds = (
                Credentials.from_service_account_file(cpath)
                .with_subject(_config["googlelookup"])
                .with_scopes(["https://www.googleapis.com/auth/" + "admin.directory.user.readonly"])
            )

            # Prepare for request
            authed_session = google.auth.transport.requests.AuthorizedSession(admincreds)

            # Get details
            userinfo_admin = authed_session.get(
                "https://admin.googleapis.com/admin/directory/v1/users/"
                + "{}?projection=full&viewType=admin_view".format(idtoken["sub"])
            )

            uia_js = userinfo_admin.json()

            if uia_js and _config["googleherd"] in uia_js:
                out_token["herd"] = uia_js[_config["googleherd"]][0]["value"]
                out_token["username"] = uia_js["name"]["givenName"] + uia_js[_config["googleherd"]][0]["value"]

            if "fullname" not in out_token and "name" in uia_js and "fullName" in uia_js["name"]:
                out_token["fullname"] = uia_js["name"]["fullName"]

    if out_token:
        return out_token

    return None


def authorized(app, method):
    """
    Return whatever we have authenticated and authorized
    through the specified method.
    """

    auth = {"google": google_authorized}

    try:
        return auth[method]()
    except KeyError:
        return False


def get_persistent(method):
    """
    Get the persistent identifier for the specified method.
    """
    pers = {"google": google_persistent}

    return pers[method]()


def get_autocreate(method):
    """
    Return the autocreate attribute for the specified method.
    """
    if method in _autocreate:
        return True
    return False


def get_account_details(method):
    """
    Get the e-mail provided for the specified method (may not work)
    """
    ad = {"google": google_details}

    return ad[method]()
