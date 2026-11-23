"""Create the account of a member who signed in with a code for the first time."""

from flask import Blueprint, current_app, jsonify, request, session
from utils import login_account, login_code

from blueprints.common import problem

login_account_bp = Blueprint("login_account", __name__, url_prefix="/api/v2/login")


@login_account_bp.post("/skapa-konto")
def create_account():
    if not login_code.enabled():
        return problem(503, "Kodinloggning är stängd", "Försök igen senare.")
    try:
        login_code.refuse_unsafe()
    except login_code.CodeRefused:
        return problem(503, "Kodinloggning är stängd", "Försök igen senare.")

    expired = "Begär en ny kod för att skapa ditt konto."
    if not login_account.pending_valid():
        return problem(401, "Inloggningen har gått ut", expired)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("accepted") is not True or not isinstance(body.get("rules_version"), str):
        return problem(400, "Godkänn reglerna", "Läs och godkänn reglerna för användarkonton.")
    version = login_account.published_rules_version()
    if version is None:
        return problem(503, "Reglerna kunde inte hämtas", "Försök igen senare.")
    if body["rules_version"] != version:
        return problem(412, "Reglerna har ändrats", "Ladda om sidan och läs de aktuella reglerna.")
    try:
        user, generation = login_account.create_pending_account(version)
    except login_account.AccountConflict:
        return problem(
            409,
            "Det finns redan ett konto som kan vara ditt",
            "Det finns redan ett konto som kan vara ditt. Logga in med det, eller kontakta matrikelansvarig.",
        )
    except login_code.CodeLoginClosed:
        return problem(503, "Kodinloggning är stängd", "Försök igen senare.")
    except login_account.InvalidPending:
        return problem(401, "Inloggningen har gått ut", expired)

    epoch = session["logout_epoch"]
    session.clear()
    current_app.extensions["establish_session"](user, "kod", generation, verified_epoch=epoch)
    return jsonify(v2_prod_access=user.v2_prod_access)
