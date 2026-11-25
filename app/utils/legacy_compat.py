"""
Compatibility helpers for the legacy React frontend (Phase 20).

The legacy app and the v2 (Next.js) app share one Flask backend, so a few
endpoints must answer differently depending on which frontend asked. The only
reliable discriminator is the request host: the legacy frontend is served from
its own vhosts, v2 from the main site.

Both the host list and the Classroom URL are environment-overridable so a
misjudged host can be corrected without a code change.
"""

import logging
import os

from flask import current_app, request

# Outside the "herdbook" logger tree: APP.log's formatter appends the request
# URL, query string included, to every line.
logger = logging.getLogger(__name__)

DEFAULT_LEGACY_HOSTS = "stamboken.gotlandskaninen.se,test.gotlandskaninen.se,stamboken.sb.gotlandskaninen.se"

# Old production redirected non-validated Google logins here.
DEFAULT_CLASSROOM_URL = "https://classroom.google.com/c/NjE3MDI1MzY2OTAz?cjc=27x3zpg"

# What the legacy frontend calls, as (Flask endpoint, method): taken from its
# source at the commit build-and-publish.yml pins, one row per call site in
# tests/data/legacy_calls.tsv. On a legacy host these need a validated account
# (the web course), not v2_prod_access. Pairs, not URLs: legacy's
# GET /api/individual/<nr> is here, v2's PATCH on the same URL is not.
LEGACY_ENDPOINTS = frozenset(
    {
        ("breeding", "GET"),
        ("breeding_next_indidivual_number", "POST"),
        ("change_userpassword", "POST"),
        ("check_ind_intyg", "POST"),
        ("check_ind_number", "POST"),
        ("colors", "GET"),
        ("create_yearly_report_round", "POST"),
        ("delete_breeding", "POST"),
        ("delete_yearly_report_round", "DELETE"),
        ("edit_individual", "PATCH"),
        ("edit_individual", "POST"),
        ("export_yearly_reports", "GET"),
        ("external_link_handler", "GET"),
        ("external_link_handler", "POST"),
        ("external_linked_accounts_handler", "POST"),
        ("external_login_handler", "GET"),
        ("external_login_handler", "POST"),
        ("external_unlink_handler", "POST"),
        ("genebank", "GET"),
        ("genebank_individuals", "GET"),
        ("get_active_users", "GET"),
        ("get_user", "GET"),
        ("get_users", "GET"),
        ("get_yearly_report_rounds", "GET"),
        ("get_yearly_reports", "GET"),
        # The legacy Google login's OAuth redirects: no call in the source, but
        # linking Google from the settings page goes through them.
        ("google.authorized", "GET"),
        ("google.login", "GET"),
        ("herd", "GET"),
        ("herd_breeding_list", "GET"),
        ("herd_breeding_list", "POST"),
        ("herd_yearly_report", "GET"),
        ("herd_yearly_report", "POST"),
        ("individual", "GET"),
        ("issue_certificate", "GET"),
        ("issue_certificate", "POST"),
        ("login_handler", "POST"),
        ("logout", "GET"),
        ("manage_herd", "PATCH"),
        ("manage_herd", "POST"),
        ("manage_roles", "PATCH"),
        ("manage_user", "GET"),
        ("manage_user", "PATCH"),
        ("manage_user", "POST"),
        ("preview_certificate", "GET"),
        ("preview_certificate", "POST"),
        ("register_birth", "POST"),
        ("register_breeding", "PATCH"),
        ("register_breeding", "POST"),
        ("testbreed", "POST"),
        ("update_certificate", "PATCH"),
        ("update_yearly_report_round", "PATCH"),
        ("verify_certificate", "POST"),
    }
)

# Open to every logged-in account on every host. The Next.js server forwards
# the visitor's cookies to public URLs too, so a logged-in member who is not
# promoted must still reach the public functions and read her own submissions.
EXEMPT_ENDPOINTS = frozenset(
    {
        ("get_user", "GET"),
        ("logout", "GET"),
        ("login_handler", "POST"),
        ("google_token_login", "POST"),
        ("code_login.status", "GET"),
        ("code_login.request_code", "POST"),
        ("code_login.verify_code", "POST"),
        ("code_login.preview_link", "POST"),
        ("code_login.redeem_link", "POST"),
        ("external_login_handler", "GET"),
        ("external_login_handler", "POST"),
        ("google.login", "GET"),
        ("google.authorized", "GET"),
        # Linking Google to one's own account: without it an account that is
        # neither validated nor promoted could never link a new identity.
        ("external_link_handler", "GET"),
        ("external_link_handler", "POST"),
        # The public certificate verification (QR) page.
        ("certificates_v2.verify_certificate_get", "GET"),
        ("certificates_v2.verify_certificate_post", "POST"),
        # The personal report link: the exchange checks the token, and mine only lists the session's codes.
        ("rapport_link.open_link", "POST"),
        ("rapport_link.mine", "GET"),
        ("rapport_link.contacts", "GET"),
        # The public membership application (not its listing, which is GET)
        # and the genebank names its form shows.
        ("member_applications.create_application", "POST"),
        ("member_applications.list_public_genebanks", "GET"),
        # A member can still read her own submissions and manage their notices.
        ("inbox.my_uploads", "GET"),
        ("inbox.uploads_seen", "POST"),
        ("inbox.notice_count", "GET"),
        # A person's choice to show her name on the public check page (stamboken #6): she must always be able to
        # read and withdraw it in production, also once her production access is gone.
        ("certificates_v2.check_page_name", "GET"),
        ("certificates_v2.check_page_name", "PUT"),
        # Tyck till: anyone may send feedback, logged in or not, and from the demo too.
        ("tyck_till.send", "POST"),
        ("health_check", "GET"),
        # No data: the SPA shell, which also answers every unknown GET with 404.
        ("main", "GET"),
        ("static", "GET"),
    }
)

NOT_PROMOTED = "Ditt konto har inte tillgång till riktiga Stamboken än"


def legacy_hosts():
    """The hosts served by the legacy frontend, from $LEGACY_HOSTS."""
    raw = os.getenv("LEGACY_HOSTS") or DEFAULT_LEGACY_HOSTS
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def legacy_classroom_url():
    """Where a non-validated legacy user is sent, from $LEGACY_CLASSROOM_URL."""
    return os.getenv("LEGACY_CLASSROOM_URL") or DEFAULT_CLASSROOM_URL


def course_message():
    """What an account that has not taken the web course is told."""
    return (
        f"Du behöver gå webbkursen och bli validerad först: {legacy_classroom_url()} Frågor: admin@gotlandskaninen.se"
    )


def is_legacy_host():
    """True when the current request arrived on a host served by the legacy frontend.

    Requires nginx to forward the original Host header (proxy_set_header Host $host).
    """
    host = (request.host or "").split(":")[0].strip().lower()
    return host in legacy_hosts()


def report_link_only():
    """Only code-aware report views can opt out of account access and require the link's grant instead."""
    return request.args.get("via") == "lank" and getattr(
        current_app.view_functions.get(request.endpoint), "accepts_report_code", False
    )


def refusal(endpoint, method, user):
    """
    The access rules for a logged-in `user`: the 403 text when this request
    is refused, None when it may proceed. On a legacy host the legacy
    frontend's functions need `validated`; everything else, on every host,
    needs v2_prod_access or admin.
    """
    pair = (endpoint, "GET" if method == "HEAD" else method)
    if pair in EXEMPT_ENDPOINTS or report_link_only():
        return None
    if is_legacy_host() and pair in LEGACY_ENDPOINTS:
        message = None if user.validated else course_message()
    else:
        message = None if user.v2_promoted else NOT_PROMOTED
    if message:
        logger.warning("Access rules refused %s %s", pair[1], endpoint)
    return message
