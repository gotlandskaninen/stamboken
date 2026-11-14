"""
This file contains data access and manipulation functions to interact with the
database.
"""

# pylint: disable=too-many-lines

import csv
import io
import json
import logging
import math
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from peewee import (
    JOIN,
    Case,
    DatabaseError,
    DoesNotExist,
    IntegrityError,
    OperationalError,
    PeeweeException,
    Value,
    fn,
)

# pylint: disable=import-error

from utils.database import DB_PROXY as DATABASE  # isort:skip
from utils.database import Authenticators  # isort: skip
from utils.database import Bodyfat  # isort: skip
from utils.database import Breeding  # isort: skip
from utils.database import Bunny  # isort: skip
from utils.database import Color  # isort: skip
from utils.database import Genebank  # isort: skip
from utils.database import Herd  # isort: skip
from utils.database import HerdTracking  # isort: skip
from utils.database import Individual  # isort: skip
from utils.database import User  # isort: skip
from utils.database import Weight  # isort: skip
from utils.database import next_individual_number  # isort: skip
from utils.database import ACTIVE_WINDOW_DAYS  # isort: skip
from utils.database import OUTSIDE_GENEBANK_HERDS  # isort: skip
from utils.database import PRIVACY_LEVELS  # isort: skip
from utils.database import ht_not_voided  # isort: skip
from utils.database import ht_order_desc  # isort: skip
from utils.database import latest_ht_per_individual  # isort: skip
from utils.database import lock_individuals  # isort: skip
from utils.database import not_voided  # isort: skip
from utils.database import validate_date  # isort: skip
from utils.database import YearlyHerdReport

from utils.database import AuditLog  # isort: skip
from utils.database import AUDITED_TABLES  # isort: skip
from utils.database import IndividualDisease  # isort: skip

from utils.database import YearlyReportRound  # isort:skip
from utils.csv_safe import csv_cell  # isort:skip
from utils.herd_tracking import BIRTH_HERD_CHANGED_REASON  # isort:skip
from utils.herd_tracking import HerdTrackingError  # isort:skip
from utils.herd_tracking import record_herd_tracking, replace_birth_row  # isort:skip
from utils.herd_tracking import is_manager_of  # isort:skip
from utils.individual_number_v2 import LITTER_SIZE6W_ABOVE_BORN, RosterAliveExceeds6w  # isort:skip
from utils.individual_number_v2 import suggest_litter_number, validate_first_certificate  # isort:skip
from utils.individual_number_v2 import litter_mismatch, parse_number  # isort:skip
from utils.pedigree_guard import CYCLE_PROBLEM, pedigree_cycle_error  # isort:skip
from utils import number_assets  # isort:skip
from utils.individual_commands import canonical_breeding_id  # isort:skip
from utils.individual_commands import lock_individual_for_edit  # noqa: F401  # isort:skip  re-exported for da.
from utils.individual_commands import update_birth_date_herd_tracking  # isort:skip
from utils.individual_commands import update_bodyfat, update_weights  # isort:skip
from utils.individual_commands import IndividualRefused, execute, purge_command_free_text  # isort:skip
from utils.individual_commands import known_color, known_litter, known_origin_herd, known_parent  # isort:skip
from utils.individual_legacy import translate  # isort:skip

from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)  # isort:skip

from werkzeug.exceptions import HTTPException  # isort:skip

logger = logging.getLogger("herdbook.da")


class ValidationError(HTTPException):
    """Domain-rule violation that surfaces as RFC 9457 problem+json.

    Subclasses werkzeug's HTTPException so a bare ``raise`` anywhere in
    the data-access layer becomes a finished HTTP response — Flask
    converts HTTPExceptions automatically (TRAP_HTTP_EXCEPTIONS is off).
    This is how the last-admin invariant surfaces as 409 through the
    UNTOUCHED legacy /api/manage/role route: the shared helper raises,
    zero route handlers change (locked policy: zero
    legacy endpoint modifications).
    """

    code = 409

    def __init__(self, problem_type, detail, title=None, status=409):
        super().__init__(description=detail)
        self.code = status
        self.problem_type = problem_type
        # Response contract: title is the first sentence unless
        # given explicitly.
        self.title = title or detail.split(".")[0]
        self.detail = detail

    def get_body(self, *args, **kwargs):
        return json.dumps(
            {
                "type": self.problem_type,
                "title": self.title,
                "status": self.code,
                "detail": self.detail,
            }
        )

    def get_headers(self, *args, **kwargs):
        return [("Content-Type", "application/problem+json")]


# Breeding validation constants (days)
MIN_PARENT_AGE_DAYS = int(os.getenv("MIN_PARENT_AGE_DAYS", 180))  # 6 months
MIN_GESTATION_DAYS = int(os.getenv("MIN_GESTATION_DAYS", 26))
MAX_GESTATION_DAYS = int(os.getenv("MAX_GESTATION_DAYS", 38))
MIN_DAYS_BETWEEN_LITTERS = int(os.getenv("MIN_DAYS_BETWEEN_LITTERS", 35))
MAX_PARENT_AGE_WARNING_DAYS = int(os.getenv("MAX_PARENT_AGE_WARNING_DAYS", 1825))  # 5 years

# Helper functions


def _to_date(value):
    """Convert a datetime or date to a date object."""
    if isinstance(value, datetime):
        return value.date()
    return value


def was_in_herd_at_date(individual_id, herd_id, target_date):
    """Check if individual was in herd_id at target_date using HerdTracking history.

    Finds the latest HerdTracking entry with herd_tracking_date <= target_date.
    If that entry's herd matches herd_id, the individual was there at that date.
    Same-day order is `ht_order_desc()` (BIRTH sorts last within a day, then id desc); voided rows are ignored.
    """
    tracking = (
        HerdTracking.select()
        .where(
            HerdTracking.individual == individual_id,
            HerdTracking.herd_tracking_date <= target_date,
            ht_not_voided(),
        )
        .order_by(*ht_order_desc())
        .first()
    )
    if tracking is None:
        return False
    return tracking.herd_id == herd_id


def mother_belongs_to_herd(mother, herd_id, target_date):
    """Check that a doe may be used for a breeding registered in herd_id at target_date.

    The legacy breeding form offers every doe CURRENTLY in the herd, and the
    textbook case is a doe bought pregnant: the mating happened at the seller's,
    but it is the buyer who registers it. So the doe qualifies if she is in the
    herd now OR was in it at the date. Only a doe the user has never owned is
    refused.

    A null mother ("utan kull" litters) belongs to no herd — same answer as the
    plain HerdTracking lookup gave for a missing individual.
    """
    if mother is None:
        return False
    if was_in_herd_at_date(mother.id, herd_id, target_date):
        return True
    return mother.current_herd.id == herd_id


def validate_parent_roles(mother, father):
    """Validate the parent PAIR itself: identity and sex.

    These are not date constraints and never a historical-data artefact — the
    same individual cannot be both parents, and a parent cannot hold a role its
    sex contradicts. Kept separate from ``validate_breeding_dates`` so callers
    that may downgrade date findings to warnings (``update_breeding``) cannot
    downgrade these by accident.

    Returns a list of error messages (blocks save), in Swedish.
    """
    errors = []

    if mother and father and mother.id == father.id:
        errors.append("Samma individ kan inte vara både mor och far")

    sex_error = False
    if mother and mother.sex and mother.sex != "female":
        sex_error = True
    if father and father.sex and father.sex != "male":
        sex_error = True
    if sex_error:
        errors.append("Fel kön för föräldraroll")

    return errors


def validate_breeding_dates(
    breed_date=None,
    birth_date=None,
    mother=None,
    father=None,
    exclude_breeding_id=None,
    litter_size=None,
    include_parent_roles=True,
):
    """Validate date constraints for breeding/birth records.

    Returns tuple of (errors, warnings).
    errors = list of error messages (blocks save).
    warnings = list of warning messages (informational, does not block).
    All messages in Swedish for frontend display.

    ``include_parent_roles=False`` leaves out the identity/sex findings of
    ``validate_parent_roles`` so a caller can keep them blocking while treating
    the date findings differently; that caller must then call
    ``validate_parent_roles`` itself.
    """
    errors = []
    warnings = []
    today = date.today()

    breed_date_d = _to_date(breed_date) if breed_date else None
    birth_date_d = _to_date(birth_date) if birth_date else None

    if breed_date_d and breed_date_d > today:
        errors.append("Parningsdatum kan inte vara i framtiden.")

    if birth_date_d and birth_date_d > today:
        errors.append("Födelsedatum kan inte vara i framtiden.")

    # Check parent age at birth
    if birth_date_d:
        if mother and mother.breeding and mother.breeding.birth_date:
            mother_birth = _to_date(mother.breeding.birth_date)
            if birth_date_d < mother_birth:
                errors.append("Födelsedatum kan inte vara före moderns födelsedatum.")
            elif (birth_date_d - mother_birth).days < MIN_PARENT_AGE_DAYS:
                errors.append(f"Modern måste vara minst {MIN_PARENT_AGE_DAYS} dagar gammal vid kullens födelse.")
        if father and father.breeding and father.breeding.birth_date:
            father_birth = _to_date(father.breeding.birth_date)
            if birth_date_d < father_birth:
                errors.append("Födelsedatum kan inte vara före faderns födelsedatum.")
            elif (birth_date_d - father_birth).days < MIN_PARENT_AGE_DAYS:
                errors.append(f"Fadern måste vara minst {MIN_PARENT_AGE_DAYS} dagar gammal vid kullens födelse.")

    # Check parent age at breeding
    if breed_date_d:
        if mother and mother.breeding and mother.breeding.birth_date:
            mother_birth = _to_date(mother.breeding.birth_date)
            if breed_date_d < mother_birth:
                errors.append("Parningsdatum kan inte vara före moderns födelsedatum.")
        if father and father.breeding and father.breeding.birth_date:
            father_birth = _to_date(father.breeding.birth_date)
            if breed_date_d < father_birth:
                errors.append("Parningsdatum kan inte vara före faderns födelsedatum.")

    # Gestation window
    if breed_date_d and birth_date_d:
        gestation = (birth_date_d - breed_date_d).days
        if gestation < MIN_GESTATION_DAYS or gestation > MAX_GESTATION_DAYS:
            errors.append(
                f"Dräktighetsperioden måste vara mellan {MIN_GESTATION_DAYS} och "
                f"{MAX_GESTATION_DAYS} dagar (var {gestation} dagar)."
            )

    # Identity and sex validation (same findings, extracted so update_breeding
    # can keep them blocking while downgrading the date findings).
    if include_parent_roles:
        errors += validate_parent_roles(mother, father)

    # Fetch mother's breeding records once for all mother-related checks
    mother_breedings = []
    if mother and (birth_date_d or breed_date_d):
        query = Breeding.select().where(Breeding.mother == mother)
        if exclude_breeding_id:
            query = query.where(Breeding.id != exclude_breeding_id)
        mother_breedings = list(query)

    # Overlapping birth check
    if birth_date_d and mother:
        for b in mother_breedings:
            if not b.birth_date:
                continue
            existing_birth = _to_date(b.birth_date)
            days_diff = abs((birth_date_d - existing_birth).days)
            if days_diff < MIN_DAYS_BETWEEN_LITTERS:
                errors.append("Honan har redan en kull registrerad inom 35 dagar")
                break

    # Mating during gestation check
    if breed_date_d and mother:
        for b in mother_breedings:
            if not b.breed_date:
                continue
            existing_breed = _to_date(b.breed_date)
            gestation_end = existing_breed + timedelta(days=MAX_GESTATION_DAYS)
            if b.birth_date:
                if _to_date(b.birth_date) < breed_date_d:
                    continue
            if existing_breed <= breed_date_d <= gestation_end:
                errors.append("Honan är redan dräktig under detta datum")
                break

    # --- Warnings (non-blocking) ---

    # Parent older than 5 years at birth
    if birth_date_d:
        if mother and mother.breeding and mother.breeding.birth_date:
            mother_birth = _to_date(mother.breeding.birth_date)
            if (birth_date_d - mother_birth).days > MAX_PARENT_AGE_WARNING_DAYS:
                warnings.append("Modern är över 5 år gammal vid kullens födelse")
        if father and father.breeding and father.breeding.birth_date:
            father_birth = _to_date(father.breeding.birth_date)
            if (birth_date_d - father_birth).days > MAX_PARENT_AGE_WARNING_DAYS:
                warnings.append("Fadern är över 5 år gammal vid kullens födelse")

    # More than 4 litters per year for same mother
    if birth_date_d and mother:
        year_start = date(birth_date_d.year, 1, 1)
        year_end = date(birth_date_d.year, 12, 31)
        same_year_count = sum(
            1 for b in mother_breedings if b.birth_date and year_start <= _to_date(b.birth_date) <= year_end
        )
        if same_year_count >= 4:
            warnings.append("Modern har redan 4 eller fler kullar detta år")

    # Litter size > 12
    if litter_size is not None and litter_size > 12:
        warnings.append("Ovanligt stor kull (över 12 ungar)")

    # Close inbreeding (parent-child or sibling pair)
    if mother and father:
        is_close_inbreeding = False
        mb = mother.breeding if mother.breeding_id else None
        fb = father.breeding if father.breeding_id else None

        # Parent-child: one is a parent of the other
        if mb and father.id in (mb.father_id, mb.mother_id):
            is_close_inbreeding = True
        if fb and mother.id in (fb.father_id, fb.mother_id):
            is_close_inbreeding = True

        # Siblings: same litter, full siblings, or half-siblings
        if mb and fb:
            if mother.breeding_id == father.breeding_id:
                is_close_inbreeding = True
            elif (
                mb.mother_id
                and mb.father_id
                and fb.mother_id
                and fb.father_id
                and mb.mother_id == fb.mother_id
                and mb.father_id == fb.father_id
            ):
                is_close_inbreeding = True
            elif (mb.mother_id and fb.mother_id and mb.mother_id == fb.mother_id) or (
                mb.father_id and fb.father_id and mb.father_id == fb.father_id
            ):
                is_close_inbreeding = True

        if is_close_inbreeding:
            warnings.append("Nära inavelsparning (förälder-avkomma eller syskonpar)")

    return errors, warnings


# User functions


def add_user(form, user_uuid=None):
    """
    if the user identified by `user_uuid` has admin or manager rights, the new
    user described by `form` is added to the database.

    the given form should be a dictionary on the form:
    {
        email: <string value>
        password: <string value>
        validated?: <boolean>
    }
    and the response will be on the format:
        JSON: {
                status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
                message?: string,
                data: any
            }
    """
    user = fetch_user_info(user_uuid)
    if user is None or not (user.is_admin or user.is_manager):
        return {"status": "error", "message": "forbidden"}

    email = form.get("email", None)
    password = form.get("password", None)
    username = form.get("username", None)
    validated = form.get("validated", False)
    privileges = [
        {"level": "viewer", "genebank": 1},
        {"level": "viewer", "genebank": 2},
    ]
    if not email or not password:
        return {"status": "error", "message": "missing data"}

    with DATABASE.atomic():
        if User.select().where(User.email == email).first():
            return {"status": "error", "message": "already exists"}

    user = register_user(email, password, username, validated, privileges)
    return {"status": "created", "data": user.id}


def register_user(
    email,
    password,
    username=None,
    validated=False,
    privileges=None,
    fullname=None,
):
    """
    Creates a new user from an e-mail and password, returning the new user
    object.
    """
    if privileges is None:
        privileges = []

    # Don't create a new user if the email exists already
    try:
        user = User.select().where(User.email == email).get()
    except DoesNotExist:
        # Create user
        user = User(
            email=email,
            uuid=uuid.uuid4().hex,
            username=username,
            fullname=fullname,
            validated=validated,
            privileges=privileges,
        )
        with DATABASE.atomic():
            user.save()

    # Update to make sure to get the correct id
    user = User.select().where(User.email == email).get()
    logger.info(f"Registered User {user.as_dict()}")

    # If no password is provided, don't create an authenticator
    if not password:
        return user

    try:
        # If we have a password authenticator already, update it instead of creating a new.
        authenticator = (
            Authenticators.select().where((Authenticators.user == user.id) & (Authenticators.auth == "password")).get()
        )
        authenticator.auth_data = generate_password_hash(password)
    except DoesNotExist:
        authenticator = Authenticators(
            user=user.id,
            auth="password",
            auth_data=generate_password_hash(password),
        )
    with DATABASE.atomic():
        authenticator.save()

    return user


class InactiveAccountError(Exception):
    """Login attempt for a deactivated account (layer 1)."""


def authenticate_user(name, password):
    """
    Authenticates an email or username and password against the database.
    Returns the user info for the authenticated user on success, or None on
    failure.
    """
    if not name or not password:
        return None
    try:
        with DATABASE.atomic():
            user_info = User.select().where((User.email == name) | (User.username == name)).get()
            if user_info and not user_info.is_active:
                logger.info("Login attempt for inactive account %s", name)
                raise InactiveAccountError()
            if user_info:
                authenticator = (
                    Authenticators.select()
                    .where((Authenticators.auth == "password") & (Authenticators.user == user_info.id))
                    .get()
                )
        if check_password_hash(authenticator.auth_data, password):
            return user_info
    except DoesNotExist:
        # Perform password check regardless of username to prevent timing
        # attacks
        check_password_hash("This-always-fails", password)
    logger.info("Failed login attempt for %s", name)
    return None


def change_password(active_user, changed_user, form):
    """
    Changes password for user changed_user. Returns
    something that evaluates as True on success.
    """
    if not active_user or not changed_user or not form:
        logger.info("Bad call to change_password, somethings is missing)")
        return None

    if not active_user.is_admin:
        try:
            authenticator = (
                Authenticators.select()
                .where((Authenticators.user == changed_user) & (Authenticators.auth == "password"))
                .get()
            )
            if not check_password_hash(authenticator.auth_data, form["oldpassword"]):
                # Incorrect password supplied
                return None
        except PeeweeException:
            # Non-users need a password set to change it. Fall out on any other
            # exception as well.
            return None

    try:
        # If we have a password authenticator already, update it instead of creating a new.
        authenticator = (
            Authenticators.select()
            .where((Authenticators.user == changed_user) & (Authenticators.auth == "password"))
            .get()
        )
        authenticator.auth_data = generate_password_hash(form["newpassword"])
    except DoesNotExist:
        authenticator = Authenticators(
            user=changed_user,
            auth="password",
            auth_data=generate_password_hash(form["password"]),
        )
    with DATABASE.atomic():
        authenticator.save()

    return True


def authenticate_with_credentials(method, ident):
    """
    Authenticates a user through an external authentication service.
    Returns the user info for the authenticated user on success, or None on
    failure.
    """
    if not method or not ident:
        return None
    try:
        with DATABASE.atomic():
            authenticator = (
                Authenticators.select()
                .where((Authenticators.auth == method) & (Authenticators.auth_data == ident))
                .get()
            )
        if authenticator:
            user_info = User.select().where(User.id == authenticator.user).get()

            if user_info:
                return user_info
    except DoesNotExist:
        pass

    logger.info("Failed login attempt for service %s persistent id %s", method, ident)
    return None


def link_account(user, method, ident):
    """
    Registers an account linked to an external authentication service. Returns
    something that evaluates as True on success.
    """
    if not method or not ident or not user:
        return None

    # Allows at most one identity for each method to be linked to this account.
    unlink_account(user, method)

    try:
        with DATABASE.atomic():
            authenticator = (
                Authenticators.select()
                .where((Authenticators.auth == method) & (Authenticators.auth_data == ident))
                .get()
            )
        if authenticator:
            # Someone else has this identity registered, do not allow the same external identity
            # for multiple users
            return None
    except DoesNotExist:
        pass

    try:
        authenticator = Authenticators(user=user.id, auth=method, auth_data=ident)
        with DATABASE.atomic():
            authenticator.save()
        logger.info("Linked %s to %s persistent id %s", user.username, method, ident)
        return user
    except PeeweeException as auth_except:
        logger.info(
            "Error (%s) while linking %s to %s persistent id %s",
            auth_except,
            user.username,
            method,
            ident,
        )

    logger.info(
        "Failed link attempt for user %s service %s persistent id %s",
        user.username,
        method,
        ident,
    )
    return None


def unlink_account(user, method):
    """
    Removes any linked identities for method method. Return somethings that
    evaluates to false on failure.
    """
    if not method or not user:
        return None
    try:
        with DATABASE.atomic():
            Authenticators.delete().where((Authenticators.user == user.id) & (Authenticators.auth == method)).execute()

        return True
    except DoesNotExist:
        return None

    logger.info("Failed to unlink idenities for service %s user %d", method, user.id)
    return None


def linked_accounts(user):
    """
    Returns any linked methods for the given account.
    """
    if not user:
        return None
    try:
        with DATABASE.atomic():
            auths = Authenticators.select().where(
                (Authenticators.user == user.id) & (Authenticators.auth != "password")
            )

        return [x.auth for x in auths]
    except DoesNotExist:
        return None

    logger.info("Failed to list linked idenities for user %d", user.id)
    return None


def fetch_user_info(user_id):
    """
    Fetches user information for a given user id.

    Returns None for deactivated accounts (layer 3): this is the
    single session→User resolver — flask-login's user_loader AND legacy
    handlers like /api/user — so an inactive user's existing session
    stops resolving on their next request. No Redis purge needed.
    """
    try:
        with DATABASE.atomic():
            user = User.get(User.uuid == user_id)
    except DoesNotExist:
        return None
    if not user.is_active:
        return None
    return user


def get_users(user_uuid=None):
    """
    Returns all users that the logged in user has access to. This is all users
    for admin, all users except admin users for managers, and None for regular
    users.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return None
    try:
        if not user.is_admin and not user.is_manager:
            return None
        with DATABASE.atomic():
            users = list(User.select())
        if not user.is_admin:
            users = [user for user in users if not user.is_admin]

        return [
            {
                "email": u.email,
                "name": u.username,
                "id": u.id,
                "fullname": u.fullname,
            }
            for u in users
        ]
    except DoesNotExist:
        return None


def get_active_users(minutes, user_uuid=None):
    """
    Returns a list of currently active users

    """
    user = fetch_user_info(user_uuid)
    time_ago = datetime.now() - timedelta(minutes=minutes)
    if user is None:
        return {"status": "error", "message": "Not logged in"}
    if not (user.is_admin or user.is_manager):
        return {"status": "error", "message": "Forbidden"}
    try:
        active_users = User.select().where(User.last_active >= time_ago)
    except DoesNotExist:
        return None
    return [
        {
            "username": user.username,
            "fullname": user.fullname,
            "last_active": user.last_active,
        }
        for user in active_users
    ]


def get_user(user_id, user_uuid=None):
    """
    Returns the user with id `user_id`, if the user identified by
    `user_uuid` has admin or manager privileges. Note that the user does not
    need manager privileges over any particular genebank or herd.
    Returns:
        JSON: {
                status: 'success' | 'error',
                message?: <error message>,
                data?: <user-data>
            }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}
    if not (user.is_admin or user.is_manager):
        return {"status": "error", "message": "Forbidden"}
    try:
        with DATABASE.atomic():
            target = User.get(int(user_id))
    except DoesNotExist:
        return {"status": "error", "message": "Unknown user"}

    return {
        "status": "success",
        "data": {
            "id": target.id,
            "email": target.email,
            "username": target.username,
            "fullname": target.fullname,
            "validated": target.validated,
            "privileges": target.privileges,
        },
    }


def update_user(form, user_uuid=None):
    """
    Takes a role change description `form` and updates the user given by
    `form.id` with the values in `form`, and returns a status message.

    The input data should be formatted like:
        {id: <number>, email: <string>, validated: <boolean>}

    The return value will be formatted as:
        JSON: {
                status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
                message?: string,
            }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "not logged in"}

    # Check data
    if (
        not isinstance(form, dict)
        or not form.get("id", None)
        or not form.get("email", None)
        or form.get("validated") not in [True, False]
    ):
        return {"status": "error", "message": f"malformed request: {form}"}

    # Check permissions - allow users to update e-mail only
    if not (user.is_admin or user.is_manager) and (form.get("validated") or form.get("username")):
        return {"status": "error", "message": "forbidden"}

    # Self-service callers may only edit their own account.
    if not (user.is_admin or user.is_manager) and str(form["id"]) != str(user.id):
        return {"status": "error", "message": "forbidden"}

    if not (user.is_admin or user.is_manager):
        # Mark user supplied e-mail as false
        form["validated"] = False

    # check target user
    try:
        with DATABASE.atomic():
            target_user = User.get(form["id"])
    except DoesNotExist:
        return {"status": "error", "message": "unknown user"}

    # Managers never edit admin accounts (get_users hides them too); the
    # email is the password-login key, so that edit is a takeover.
    if not user.is_admin and target_user.is_admin and target_user.id != user.id:
        return {"status": "error", "message": "forbidden"}

    # No taking an address another account holds: it is the password-login key
    # (stop-gap; CMS identity keys on google_email, never on this field).
    if (
        form["email"] != target_user.email
        and User.select()
        .where((fn.LOWER(User.email) == str(form["email"]).lower()) & (User.id != target_user.id))
        .exists()
    ):
        return {"status": "error", "message": "email already in use"}

    # update target user data if needed
    changed = []
    for field in ["email", "username", "validated", "fullname"]:
        if field in form and getattr(target_user, field) != form[field]:
            setattr(target_user, field, form[field])
            changed.append(getattr(User, field))

    if changed:
        # Only the changed columns: target_user was read without a lock, so a
        # full-row save would write back a stale is_active/_privileges.
        with DATABASE.atomic():
            target_user.save(only=changed)
        return {"status": "updated"}

    return {"status": "unchanged"}


_ALLOWED_LEVELS = ("admin", "matrikel_admin", "manager", "helper", "viewer", "owner")


def validate_privileges(privileges):
    """Validate a proposed _privileges list before writing to hbuser.

    Accepts a list of dicts. Each dict must match one of these shapes:

    - {"level": "admin"}
    - {"level": "matrikel_admin"}
    - {"level": "manager", "genebank": <int>}
    - {"level": "helper",  "genebank": <int>}
    - {"level": "viewer",  "genebank": <int>}
    - {"level": "owner",   "herd":     <int>}   # numeric Herd.id

    Rejects unknown level names, missing required keys, wrong value types
    (including string-encoded integers — the picker always submits real
    ints), and unexpected extra keys. Returns the validated list
    (normalised — level strings stripped of surrounding whitespace).
    Raises ValueError with a Swedish user-facing message on any failure.

    Applied to every WRITE to hbuser._privileges. Reads stay
    lenient — existing rows may have been written before this validator
    existed; a strict read would reject legacy shapes.
    """
    if not isinstance(privileges, list):
        raise ValueError(f"_privileges måste vara en lista, inte {type(privileges).__name__}.")
    validated = []
    for entry in privileges:
        if not isinstance(entry, dict):
            raise ValueError(f"Varje behörighetspost måste vara ett objekt, inte {type(entry).__name__}.")
        if "level" not in entry:
            raise ValueError("Behörighetsposten saknar 'level'.")

        level = entry["level"]
        if isinstance(level, str):
            level = level.strip()

        if level not in _ALLOWED_LEVELS:
            raise ValueError(f"Okänd nivå: {level!r}. Tillåtna: {', '.join(_ALLOWED_LEVELS)}.")

        extra_keys = set(entry.keys()) - {"level"}

        if level in ("admin", "matrikel_admin"):
            if extra_keys:
                raise ValueError(f"Nivå {level!r} får inte ha extra fält (fick {sorted(extra_keys)}).")
            validated.append({"level": level})

        elif level in ("manager", "helper", "viewer"):
            if "genebank" not in entry:
                raise ValueError(f"Nivå {level!r} kräver 'genebank'.")
            gb = entry["genebank"]
            # bool is a subclass of int in Python — exclude explicitly.
            if not isinstance(gb, int) or isinstance(gb, bool):
                raise ValueError(f"'genebank' måste vara heltal (fick {type(gb).__name__} {gb!r}).")
            unexpected = extra_keys - {"genebank"}
            if unexpected:
                raise ValueError(f"Nivå {level!r} har oväntade fält: {sorted(unexpected)}.")
            validated.append({"level": level, "genebank": gb})

        elif level == "owner":
            if "herd" not in entry:
                raise ValueError("Nivå 'owner' kräver 'herd'.")
            herd = entry["herd"]
            if not isinstance(herd, int) or isinstance(herd, bool):
                raise ValueError(f"'herd' måste vara heltal (Herd.id) (fick {type(herd).__name__} {herd!r}).")
            unexpected = extra_keys - {"herd"}
            if unexpected:
                raise ValueError(f"Nivå 'owner' har oväntade fält: {sorted(unexpected)}.")
            validated.append({"level": "owner", "herd": herd})

    return validated


def _lock_role_rows(target_user_id):
    """Acquire ALL row locks a role transaction needs in ONE
    ordered query — the target user plus every current admin — sorted
    ascending by id. Concurrent role transactions acquire locks in the
    same global order, so the second waits instead of deadlocking
    (no AB-BA cycle). Must run as the FIRST statement inside the
    caller's atomic(). Returns the locked User rows.
    """
    return list(
        User.select()
        .where((User.id == target_user_id) | (User._privileges.contains('{"level": "admin"}')))
        .order_by(User.id)  # global lock order — prevents AB-BA
        .for_update()
    )


def _count_current_admins(locked_rows, exclude_user_id=None):
    """Count admins among the ALREADY-LOCKED rows — no second query (a
    fresh SELECT could see rows the lock query did not cover).
    Only ACTIVE users count toward the invariant.
    """
    return sum(
        1
        for u in locked_rows
        if u.id != exclude_user_id and u.is_active and any(p.get("level") == "admin" for p in u.privileges)
    )


def _is_deadlock(exc):
    """SQLSTATE 40P01 detection through the peewee wrapper. psycopg2 sets
    .pgcode on the ORIGINAL exception; peewee re-raises its own
    OperationalError with the original chained (__cause__/__context__)."""
    for candidate in (exc, exc.__cause__, exc.__context__):
        if candidate is not None and getattr(candidate, "pgcode", None) == "40P01":
            return True
    return False


def set_account_active(u_id, active, actor_user_id=None):
    """
    Activate/deactivate an account.

    Guard order matters: the last-active-admin
    invariant is checked FIRST, inside the ordered-lock
    transaction — the only endpoint-reachable violation is the sole
    ACTIVE admin deactivating themselves, and it must surface as
    `last-admin`. The self-guard covers the remaining self case.

    Raises ValidationError("last-admin", ...) / ("self-deactivation", ...)
    on guard violation, ValueError("user-not-found") for unknown ids.
    """
    for attempt in (1, 2):  # Single 40P01 retry (belt)
        try:
            with DATABASE.atomic():
                # FIRST statement: ordered FOR UPDATE of target + all admins.
                locked = _lock_role_rows(u_id)
                target = next((u for u in locked if u.id == u_id), None)
                if target is None:
                    raise ValueError("user-not-found")
                if not active and _count_current_admins(locked, exclude_user_id=u_id) == 0:
                    raise ValidationError(
                        "last-admin",
                        "Kan inte inaktivera sista aktiva admin-kontot. Minst en aktiv admin måste finnas.",
                    )
                if not active and actor_user_id == u_id:
                    raise ValidationError(
                        "self-deactivation",
                        "Du kan inte inaktivera kontot du själv är inloggad med.",
                    )
                target.is_active = bool(active)
                target.save()
                return {"id": target.id, "is_active": bool(target.is_active)}
        except OperationalError as exc:
            # SQLSTATE 40P01 (deadlock_detected) — rare re-ordering under
            # READ COMMITTED; retry once (belt), then surface. _is_deadlock
            # unwraps the peewee wrapper (pgcode lives on the chained
            # psycopg2 exception), matching update_role's retry.
            if attempt == 2 or not _is_deadlock(exc):
                raise


def _is_int_id(value):
    """A real integer id: bool is an int subclass, str/float ids are not ids."""
    return isinstance(value, int) and not isinstance(value, bool)


def update_role(operation, user_uuid=None, skip_role_check=False):
    """
    Takes a role change description `operation`, and returns a status message.

    The input data should be formatted like:
        {action: add | remove,
         role: owner | manager | helper | viewer | admin | matrikel_admin,
         user: <id>,
         herd | genebank: <id>
        }

    The return value will be formatted like:
        JSON: {
            status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
            message?: string,
            data?: any
        }

    Optionally takes a flag to skip role verification for system use.

    The target fetch, the last-admin
    invariant, and the _privileges write share ONE atomic() whose first
    statement is the ordered lock query (_lock_role_rows). Raises
    ValidationError("last-admin") — rendered by Flask as HTTP 409
    application/problem+json — if the write would leave zero ACTIVE
    admins. Single retry on SQLSTATE 40P01.
    """
    user = fetch_user_info(user_uuid)
    if user is None and not skip_role_check:
        return {"status": "error", "message": "not logged in"}

    # Check data
    valid = True
    message = "malformed request"
    if (
        not isinstance(operation, dict)
        or operation.get("action", {}) not in ["add", "remove"]
        or (not isinstance(operation.get("user", ""), int) and not operation.get("user", "").isdigit())
    ):
        valid = False
    elif (
        operation.get("role", {}) not in ["owner", "manager", "helper", "viewer", "admin", "matrikel_admin"]
        or (
            operation["role"] in ["manager", "helper", "viewer"]
            and not (operation.get("genebank") and _is_int_id(operation["genebank"]))
        )
        or (operation["role"] == "owner" and not (operation.get("herd") and _is_int_id(operation["herd"])))
    ):
        valid = False

    # Check permissions
    permitted = True
    if valid and operation["role"] in ("admin", "matrikel_admin"):
        # Global roles have no genebank scope, so a manager role or a genebank
        # named in the body must never authorize them.
        if not (skip_role_check or user.is_admin):
            permitted = False
            message = "forbidden"
    elif skip_role_check or user.is_manager:
        genebank = operation.get("genebank", None)
        # An owner grant is scoped by the herd's real genebank, never by one
        # named in the body. An unknown herd has no genebank, so only
        # an admin (or the system) may touch it, e.g. to clean up the entry.
        if valid and operation["role"] == "owner":
            herd = Herd.get_or_none(Herd.id == operation["herd"])
            genebank = herd.genebank_id if herd else None
        if not (skip_role_check or user.is_admin or (genebank is not None and genebank in user.is_manager)):
            permitted = False
            message = "forbidden"
    elif not user.is_admin:
        permitted = False
        message = "forbidden"

    if not valid or not permitted:
        return {"status": "error", "message": message}

    # Target fetch, last-admin invariant, and the
    # _privileges write all share ONE atomic() whose FIRST statement is
    # the ordered lock query. Single 40P01 retry as belt (rare
    # EvalPlanQual re-ordering under READ COMMITTED).
    target_id = int(operation["user"])
    target = "herd" if operation["role"] == "owner" else "genebank"

    for attempt in (1, 2):
        try:
            with DATABASE.atomic():
                # FIRST statement: ordered lock of target + all admins.
                locked = _lock_role_rows(target_id)
                target_user = next((u for u in locked if u.id == target_id), None)
                if target_user is None:
                    return {"status": "error", "message": "unknown user"}

                if operation["action"] == "remove" and operation["role"] == "admin":
                    # Att ta bort admin-nivån tar bort VARJE identisk
                    # {"level": "admin"}-post, så målet är per definition
                    # inte admin efteråt — ingen "still admin?"-simulering
                    # behövs (en filtrerad omkontroll vore tautologiskt
                    # False). Räkna övriga aktiva admins
                    # direkt ur den låsta mängden.
                    if _count_current_admins(locked, exclude_user_id=target_user.id) == 0:
                        raise ValidationError(
                            "last-admin",
                            "Den sista administratörsrollen kan inte tas bort. Minst en administratör måste finnas.",
                        )

                # Existing role-write logic, INSIDE the same atomic() so the
                # locks are held until COMMIT.
                has_role = target_user.has_role(operation["role"], operation.get(target))
                updated = False
                if has_role and operation["action"] == "remove":
                    logger.info(
                        f"User:{user.username} UPDATE: Role remove on user: "
                        f"{target_user.username} removed: {operation['role']} "
                        f"target:{operation.get(target)}"
                    )
                    target_user.remove_role(operation["role"], operation.get(target))
                    updated = True
                elif not has_role and operation["action"] == "add":
                    logger.info(
                        f"User:{user.username} UPDATE: Role added on user: "
                        f"{target_user.username} added: {operation['role']} "
                        f"target:{operation.get(target)}"
                    )
                    target_user.add_role(operation["role"], operation.get(target))
                    updated = True

            return {"status": "updated" if updated else "unchanged"}
        except OperationalError as exc:
            # SQLSTATE 40P01 (deadlock_detected): retry ONCE, then re-raise.
            # ValidationError is an HTTPException, not an OperationalError —
            # it propagates to Flask untouched (renders 409 problem+json).
            if attempt == 2 or not _is_deadlock(exc):
                raise


# Phase 17 — admin/manage helpers


def edit_genebank(gb, fields, actor):
    """
    Update allowed fields on `gb` in place (allow-list enforced in the
    route layer). The genebank audit trigger captures the change — no
    explicit audit call needed.

    `name` accepts a non-empty string.
    Returns the updated genebank as a plain dict.
    """
    for key, value in fields.items():
        if key == "name":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Fältet name måste vara en icke-tom sträng.")
            gb.name = value.strip()
    with DATABASE.atomic():
        gb.save()
    logger.info(f"User:{actor.username or actor.email} edited genebank {gb.id}")
    return {"id": gb.id, "name": gb.name}


def invalid_privacy_field(fields):
    """
    Returns the first Herd `*_privacy` column in `fields` that holds anything
    but None or a privacy level, else None. Reads treat unknown values as
    'private'; writers use this to keep them out of the table.
    """
    for key, value in fields.items():
        if key.endswith("_privacy") and key in Herd._meta.fields and value not in (None, *PRIVACY_LEVELS):
            return key
    return None


# Editable herd metadata. The original design said "phone",
# but the live Herd model has mobile_phone + wire_phone (database.py:244,
# :246) and no phone column — the real columns are used here.
HERD_EDITABLE_FIELDS = {
    "name",
    "name_privacy",
    "physical_address",
    "email",
    "mobile_phone",
    "wire_phone",
    "www",
    "is_active",
}


def _herd_owner_map():
    """
    Map numeric Herd.id -> list of owning Users, in ONE pass over hbuser.

    `_privileges` is a TEXT JSON column, so owner lookups cannot be done
    in SQL. One scan of the small hbuser table (hundreds of rows)
    replaces the per-herd scans a naive join-substitute would do.

    A herd can have MULTIPLE owners (legacy parity — e.g. museum herds
    and shared family herds); lists are sorted by user id for stable
    output.
    """
    owners = {}
    for u in User.select().order_by(User.id):
        for p in u.privileges:
            if p.get("level") == "owner" and isinstance(p.get("herd"), int):
                owners.setdefault(p["herd"], []).append(u)
    return owners


def list_all_herds(user, *, genebank_id=None, active=None, has_owner=None, search=None, page=1, page_size=50):
    """
    Admin-only cross-genebank herd list. Joins genebank name +
    owner usernames. Sorted by genebank + the numeric part of the herd
    code (an earlier design said herd.name asc, but `name` is the CONTACT person
    and NULL/empty for hundreds of rows — that order made specific herds
    impossible to find across 25 pages). `search` matches herd code,
    herd name and contact name, case-insensitively. All Python-side
    filters run BEFORE pagination so `total` and page sizes stay correct.
    Returns {"herds": [...], "total": N, "page": ..., "page_size": ...}.
    """
    if not user.is_admin:
        raise ValueError("admin-required")
    q = Herd.select(Herd, Genebank).join(Genebank)
    if genebank_id is not None:
        q = q.where(Herd.genebank == genebank_id)
    if active is not None:
        q = q.where(Herd.is_active == active)
    # Materialise before slicing: herd is a small table (~1200 rows) and
    # the owner/search filters can only run Python-side (TEXT JSON).
    herds = list(q)
    # Natural sort: G2 before G10 before G1274 (lexicographic herd-code
    # sort would interleave them).
    herds.sort(key=lambda h: (h.genebank_id, int(re.sub(r"\D", "", h.herd) or 0), h.herd))
    owners = _herd_owner_map()
    if has_owner is not None:
        herds = [h for h in herds if (h.id in owners) == has_owner]
    if search:
        needle = search.strip().lower()
        herds = [
            h
            for h in herds
            if needle in (h.herd or "").lower()
            or needle in (h.herd_name or "").lower()
            or needle in (h.name or "").lower()
        ]
    total = len(herds)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    start = (page - 1) * page_size
    rows = []
    for h in herds[start : start + page_size]:
        herd_owners = owners.get(h.id, [])
        rows.append(
            {
                "id": h.id,
                "herd": h.herd,
                "herd_name": h.herd_name,
                "name": h.name,
                "is_active": bool(h.is_active),
                "genebank_id": h.genebank_id,
                "genebank_name": h.genebank.name,
                "owner_usernames": [o.username or o.email for o in herd_owners],
            }
        )
    return {"herds": rows, "total": total, "page": page, "page_size": page_size}


def get_herd_for_admin(user, herd):
    """
    Herd payload for the adminpanel — same shape whether the
    caller is admin or manager(gb).
    """
    herd_owners = _herd_owner_map().get(herd.id, [])
    return {
        "id": herd.id,
        "herd": herd.herd,
        "herd_name": herd.herd_name,
        "name": herd.name,
        "name_privacy": herd.name_privacy,
        "physical_address": herd.physical_address,
        "email": herd.email,
        "mobile_phone": herd.mobile_phone,
        "wire_phone": herd.wire_phone,
        "www": herd.www,
        "is_active": bool(herd.is_active),
        "genebank_id": herd.genebank_id,
        "genebank_name": herd.genebank.name,
        "owners": [{"id": o.id, "username": o.username or o.email, "fullname": o.fullname} for o in herd_owners],
    }


def edit_herd(herd, fields, actor):
    """
    Update allowed fields on `herd` (allow-list enforced in the route
    layer via HERD_EDITABLE_FIELDS). The existing herd audit trigger
    captures the change — no explicit audit call.
    Returns the updated herd as get_herd_for_admin would.
    """
    bad = invalid_privacy_field(fields)
    if bad:
        raise ValueError(f"Fältet {bad} måste vara public, authenticated, private eller null.")
    # Only write fields whose value actually changed, and skip the UPDATE
    # entirely when nothing did — avoids a redundant full-row write. No explicit
    # type cast is needed: every HERD_EDITABLE_FIELDS value
    # already arrives correctly typed from the RSC action (JSON bool for
    # is_active, strings for the rest), so payload and column types match.
    changed = []
    for key, value in fields.items():
        if getattr(herd, key) != value:
            setattr(herd, key, value)
            changed.append(key)
    if changed:
        # only= : a full-row save would write the stale ownership columns back
        # over a membership/genebank change committed since the row was loaded.
        with DATABASE.atomic():
            herd.save(only=changed)
    logger.info(f"User:{actor.username or actor.email} edited herd {herd.herd} via adminpanel")
    return get_herd_for_admin(actor, herd)


# Genebank functions


def get_colors():
    """
    Returns all legal colors for all genebanks, like:

    {<genebank>: [{id: <color-id>, name: <color-name>, comment: <color-comment>}, [...]],
     [...]
    }
    """
    with DATABASE.atomic():
        return {
            genebank.name: [
                {"id": color.id, "name": color.name, "comment": color.comment}
                for color in Color.select().where(Color.genebank == genebank)
            ]
            for genebank in Genebank.select()
        }


def get_genebank(genebank_id, user_uuid=None):
    """
    Returns the information about the genebank given by `genebank_id` that is
    accessible to the user identified by `user_uuid`.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return None

    return user.get_genebank(genebank_id)


def get_genebanks(user_uuid=None):
    """
    Returns all genebanks that are accessible to the user identified by
    `user_uuid`.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return None

    data = []
    with DATABASE.atomic():
        for genebank in user.get_genebanks():
            genebank_data = genebank.short_info()
            data += [genebank_data]

    return data


# Herd functions


def herd_to_herdid(lookup_herd):
    """
    Returns the id of the herd with the given name.
    """
    with DATABASE.atomic():
        try:
            herd = Herd.get(Herd.herd == lookup_herd)
        except DoesNotExist:
            return None
        return herd.id


def get_herd(herd_id, user_uuid=None):
    """
    Returns information on the herd given by `herd_id`, including a list of all
    individuals belonging to that herd. The returned data is limited to the
    access permission of the user identified by `user_uuid`.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return None
    try:
        data = None
        with DATABASE.atomic():
            herd = Herd.get(Herd.herd == herd_id)
            data = herd.filtered_dict(user)
            data["individuals"] = []
            if data["genebank"] not in user.accessible_genebanks:
                return None

            # Holder row per individual: void-filtered, shared order. No active
            # row: the origin herd holds it, like individual detail and the explorer.
            latest = latest_ht_per_individual().alias("latest_ht")
            individuals = (
                Individual.select(Individual)
                .join(latest, JOIN.LEFT_OUTER, on=((Individual.id == latest.c.i_id) & (latest.c.rank == 1)))
                .where(fn.COALESCE(latest.c.herd, Individual.origin_herd_id) == herd.id)
                .where(not_voided())
            )

            # Create a mapping of individual numbers to their data to deduplicate
            individual_map = {}
            for individual in individuals:
                if individual.number not in individual_map:
                    individual_map[individual.number] = individual

            # Convert to list and sort by number
            unique_individuals = sorted(individual_map.values(), key=lambda x: x.number)

            # Prefetch related data
            weights = Weight.select().where(Weight.individual.in_([i.id for i in unique_individuals]))
            bodyfats = Bodyfat.select().where(Bodyfat.individual.in_([i.id for i in unique_individuals]))

            # Create a mapping of individual IDs to their weights and bodyfats
            weight_map = {}
            bodyfat_map = {}

            for weight in weights:
                if weight.individual_id not in weight_map:
                    weight_map[weight.individual_id] = []
                weight_map[weight.individual_id].append(weight)

            for bodyfat in bodyfats:
                if bodyfat.individual_id not in bodyfat_map:
                    bodyfat_map[bodyfat.individual_id] = []
                bodyfat_map[bodyfat.individual_id].append(bodyfat)

            # Get all herd tracking entries for each individual
            tracking_map = {}
            for tracking in (
                HerdTracking.select(HerdTracking, Herd)
                .join(Herd)
                .where(HerdTracking.individual.in_([i.id for i in unique_individuals]), ht_not_voided())
                .order_by(*ht_order_desc())
            ):
                if tracking.individual_id not in tracking_map:
                    tracking_map[tracking.individual_id] = []
                tracking_map[tracking.individual_id].append(
                    {
                        "herd_id": tracking.herd.id,
                        "herd": tracking.herd.herd,
                        "herd_name": tracking.herd.herd_name,
                        "date": tracking.herd_tracking_date.strftime("%Y-%m-%d")
                        if tracking.herd_tracking_date
                        else None,
                        "kind": tracking.kind,
                    }
                )

            # Attach the data to each individual
            for individual in unique_individuals:
                individual.weight_set = weight_map.get(individual.id, [])
                individual.bodyfat_set = bodyfat_map.get(individual.id, [])
                individual.herd_tracking_set = tracking_map.get(individual.id, [])

            data["individuals"] = [i.as_dict() for i in unique_individuals]
            return data
    except DoesNotExist:
        return data


def add_herd(form, user_uuid):
    """
    Adds a new herd, defined by `form`, into the database, if the given `user`
    has sufficient permissions to insert herds.
    The response will be on the format:
        JSON: {
                status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
                message?: string,
                data: any
            }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}
    try:
        genebank_id = int(form["genebank"])
        if not (user.is_admin or (user.is_manager and genebank_id in user.is_manager)):
            return {"status": "error", "message": "Forbidden"}
    except (ValueError, KeyError):
        return {"status": "error", "message": "Invalid genebank ID"}

    with DATABASE.atomic():
        try:
            Herd.select().where(Herd.herd == form["herd"]).get()
            return {"status": "error", "message": "herd ID already exists"}
        except (DoesNotExist, KeyError):
            pass
        if "id" in form:
            del form["id"]
        bad = invalid_privacy_field(form)
        if bad:
            return {"status": "error", "message": f"Invalid value for {bad}"}
        # Real columns only: Herd(**form) also took _pk, genebank_id and __data__, which let a
        # manager overwrite another genebank's herd. membership is admin-only, as in update_herd.
        locked = {"id"} | (set() if user.is_admin else {"membership"})
        herd = Herd(**{k: v for k, v in form.items() if k in Herd._meta.fields and k not in locked})
        try:
            herd.save(force_insert=True)
        except IntegrityError:
            return {"status": "error", "message": "missing data"}
        logger.info(f"User:{user.username} Added herd: {herd.short_info()}")
        return {"status": "success"}


def save_yearly_report(herd_id, form_data, user):
    try:
        # Validate herd exists and user has permission
        try:
            herd = Herd.get_by_id(herd_id)
            if not user.can_edit(herd.herd):
                return {
                    "status": "error",
                    "message": "You don't have permission to modify this herd",
                }
        except DoesNotExist:
            return {"status": "error", "message": "Invalid herd ID"}

        # Prepare the data
        report_data_json = json.dumps(form_data.get("data", {}))
        report_date = date.today()
        report_name = form_data.get("name", f"Yearly Report {report_date.year}")
        version = form_data.get("version", "1.0")
        report_round_id = form_data.get("report_round_id")
        report_year = form_data.get("report_year")

        # Validate report round
        if not report_round_id:
            return {"status": "error", "message": "Missing report round ID"}

        try:
            report_round = YearlyReportRound.get_by_id(report_round_id)

            # Validate report round is active
            if not (report_round.is_active or report_round.manually_activated):
                return {
                    "status": "error",
                    "message": "Report round is not active",
                }

            # Validate report year matches
            if report_round.report_year != report_year:
                return {
                    "status": "error",
                    "message": "Report year does not match report round year",
                }

            # Validate that no other report exists for this herd in this year
            existing_reports = (
                YearlyHerdReport.select()
                .join(YearlyReportRound)
                .where(
                    (YearlyHerdReport.herd == herd_id)
                    & (YearlyReportRound.report_year == report_year)
                    & (YearlyHerdReport.round != report_round_id)
                )
            )
            if existing_reports.exists():
                return {
                    "status": "error",
                    "message": (
                        f"A report for year {report_year} already exists for this herd in a different report round"
                    ),
                }

        except YearlyReportRound.DoesNotExist:
            return {"status": "error", "message": "Invalid report round ID"}

        # Check if a report already exists for this herd and round
        existing_report = (
            YearlyHerdReport.select()
            .where((YearlyHerdReport.herd == herd_id) & (YearlyHerdReport.round == report_round_id))
            .first()
        )

        if existing_report:
            # Update the existing report
            existing_report.data = report_data_json
            existing_report.name = report_name
            existing_report.generated_by = user.id
            existing_report.version = version
            existing_report.round = report_round_id  # Update the round
            existing_report.publish = form_data.get("publish", existing_report.publish)
            existing_report.publish_tel = form_data.get("publish_tel", existing_report.publish_tel)
            existing_report.publish_email = form_data.get("publish_email", existing_report.publish_email)
            existing_report.publish_address = form_data.get("publish_address", existing_report.publish_address)
            existing_report.save()
            return {"status": "success", "message": "Report updated"}
        else:
            # Create a new report
            YearlyHerdReport.create(
                herd=herd_id,
                report_date=report_date,
                generated_by=user.id,
                name=report_name,
                data=report_data_json,
                version=version,
                round=report_round_id,  # Link to the report round
                publish=form_data.get("publish", False),
                publish_tel=form_data.get("publish_tel", False),
                publish_email=form_data.get("publish_email", False),
                publish_address=form_data.get("publish_address", False),
            )
            return {"status": "success", "message": "Report created"}
    except Exception as e:
        logger.error(f"Error saving yearly report: {e}")
        return {"status": "error", "message": "Failed to save report"}


def update_herd(form, user_uuid):
    """
    Updates a herd, identified by `form.id`, by the values in `form`, if the
    given `user` has sufficient permissions to do so.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}
    try:
        with DATABASE.atomic():
            herd = Herd.get(form["id"])

            if not user.can_edit(herd.herd):
                return {"status": "error", "message": "Forbidden"}

            bad = invalid_privacy_field(form)
            if bad:
                return {"status": "error", "message": f"Invalid value for {bad}"}

            # Real columns only (hasattr also matches genebank_id, membership_id and
            # methods such as save). Identity/ownership columns are admin-only; the
            # legacy SPA echoes the whole herd object, so locked keys are dropped, not refused.
            locked = set() if user.is_admin else {"id", "herd", "genebank", "membership"}
            written = [key for key in form if key in Herd._meta.fields and key not in locked]
            for key in written:
                setattr(herd, key, form[key])
            if written:
                # only= : a full-row save would write the stale ownership columns back
                # over a membership/genebank change committed since the row was loaded.
                herd.save(only=written)
        logger.info(f"User:{user.username} Updated herd: {herd.short_info()}")
        return {"status": "updated"}
    except DoesNotExist:
        return {"status": "error", "message": "Unknown herd"}


# Individual functions
@number_assets.finishing
def update_origin_herd_ind(individual, new_herd, user):
    """
    Updates origin_herd + number for the individual and replaces its BIRTH row
    (void + new BIRTH in the new herd) — in one transaction.
    """
    update_logger = logging.getLogger(f"{individual.current_herd.genebank.name}_update")
    update_logger.info(
        f"{user.username},{individual.number},UPDATE origin_herd and number,"
        f"{individual.origin_herd.herd},{new_herd.herd},"
    )
    old_number = individual.number
    with DATABASE.atomic():
        individual.origin_herd = new_herd
        individual.number = new_herd.herd + "-" + individual.number.split("-")[1]
        individual.save()
        replace_birth_row(individual, user, herd=new_herd, reason=BIRTH_HERD_CHANGED_REASON)
        if individual.number != old_number:
            number_assets.record(
                individual.id, old_number, individual.number, individual.digital_certificate is not None
            )


def get_individual(individual_id, user_uuid=None):
    """
    Returns information on a given individual id, if it's accessible to the user
    identified by `user_uuid`.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return None
    try:
        with DATABASE.atomic():
            individual = Individual.select().where(Individual.number == individual_id).where(not_voided()).get()

        if individual and individual.current_herd.genebank.id in user.accessible_genebanks:
            return individual.as_dict()
        return None
    except DoesNotExist:
        return None


# Individual columns form_to_individual copies from a POST form. digital_certificate is not one:
# only issuance assigns it (IssueDigitalCertificate).
FORM_WRITABLE_FIELDS = (
    "origin_herd",
    "name",
    "certificate",
    "foot_ring",
    "number",
    "sex",
    "color",
    "color_note",
    "death_date",
    "death_note",
    "notes",
    "breeding",
    "eye_color",
    "claw_color",
    "belly_color",
    "hair_notes",
    "is_active",
    "has_photo",
    "butchered",
    "castration_date",
)


# Feel free to clean this up!
# pylint: disable=too-many-branches
def form_to_individual(form, user=None):
    """
    The rabbit a POST form describes (add_individual): the columns of FORM_WRITABLE_FIELDS, looked up
    as the write commands look them up (IR-13), unsaved and without a permission check. A rabbit that
    already has the number is returned with the values set but not saved, and add_individual refuses
    it (IR-58). Raises ValueError for an unknown value.
    """

    # check if the individual exists in the datbase
    with DATABASE.atomic():
        try:
            individual = Individual.get(Individual.number == form["number"])
        except DoesNotExist:
            individual = Individual()

    # If the form has an id - make sure that it points to the same individual as
    # the number.
    if "id" in form and form["id"] != individual.id:
        raise ValueError("Number can not be updated")

    # The write commands' lookups, in today's order, with the ValueError add_individual answers (IR-13).
    try:
        if "breeding" in form:
            form["breeding"] = known_litter(form["breeding"])
        if "color" in form and form["color"] is not None:
            form["color"] = known_color(form["color"])
        if "origin_herd" in form:
            form["origin_herd"] = known_origin_herd(form["origin_herd"]["herd"])
        for parent in ["mother", "father"]:
            if parent in form:
                form[parent] = known_parent(form[parent]["number"])
    except IndividualRefused as refused:
        raise ValueError(f"{refused}") from None

    # The paper number is a text column: decide on the text it is stored as. JSON 0 or false would pass the
    # first-certificate checks as "no certificate" and be stored as "0" or "False", a certificate.
    if form.get("certificate") is not None:
        form["certificate"] = str(form["certificate"])

    # Update the columns a form may write. An explicit allowlist, not vars(Individual): that also
    # holds voided/voided_at, id, updated_at and the FK id aliases (breeding_id, origin_herd_id,
    # color_id), which would bypass the checks on their canonical keys.
    for key in FORM_WRITABLE_FIELDS:
        if form.get(key, None) is not None:
            if key.endswith("date"):
                try:
                    datetime.strptime(form[key], "%Y-%m-%d")  # a malformed date is still a ValueError envelope
                    # IR-39, kept for now (Decision 3): a well-formed date on a new rabbit answers 500, as today.
                    raise RuntimeError(f"IR-39: {key} on a new rabbit")
                except TypeError:
                    setattr(individual, key, form[key])
            else:
                setattr(individual, key, form[key])

    return individual


def add_individual(form, user_uuid):
    """
    Adds a new individual, defined by `form`, into the database, if the given
    `user` has sufficient permissions to insert individuals into the herd
    specified in the form data.
    The response will be on the format:
        JSON: {
                status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
                message?: string,
                data: any
            }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}
    try:
        with DATABASE.atomic():
            herd = Herd.get(Herd.herd == form["herd"])
    except DoesNotExist:
        return {
            "status": "error",
            "message": "Individual must have a valid herd",
        }

    if not user.can_edit(herd.herd):
        return {"status": "error", "message": "Forbidden"}
    try:  # one canonical id for the check, the lock and the write: the ORM would truncate 2.5 to 2
        breeding_id = canonical_breeding_id(form.get("breeding"))
    except ValueError as exception:
        return {"status": "error", "message": f"{exception}"}
    if breeding_id is not None:
        form["breeding"] = breeding_id

    # Take the breeding-row lock FOR UPDATE here in add_individual (below) and hold
    # it across mint + duplicate-check + insert + HerdTracking in ONE transaction, so
    # legacy create can't race roster promotion / renumber into a colliding number.
    # (next_individual_number is now a pure read — it no longer takes the lock itself.)
    with DATABASE.atomic() as txn:
        # A new rabbit joins a litter, and is born in a herd, of its own genebank only; the
        # litter under its lock. Not "a herd the user may edit": legacy registers a bought rabbit in
        # its breeder's litter.
        if breeding_id is not None:
            litter = Breeding.select().where(Breeding.id == breeding_id).for_update().first()
            if litter is not None and litter.breeding_herd_id.genebank_id != herd.genebank_id:
                return {"status": "error", "message": "Forbidden"}
        origin = form.get("origin_herd")
        origin_herd = Herd.get_or_none(Herd.herd == origin.get("herd")) if isinstance(origin, dict) else None
        if origin_herd is not None and origin_herd.genebank_id != herd.genebank_id:
            return {"status": "error", "message": "Forbidden"}
        if form.get("number", None) is None and "breeding" in form:
            # Lock the breeding row FIRST, holding it across mint→insert so the
            # minted number can't collide with a concurrent promote/renumber.
            try:
                Breeding.select().where(Breeding.id == form["breeding"]).for_update().get()
            except DoesNotExist:
                return {"status": "error", "message": "Breeding does not exist"}
            nextind = next_individual_number(
                herd=form["herd"],
                birth_date=form["birth_date"],
                breeding_event=form["breeding"],
            )
            logger.info(f"nextind is {nextind}")
            if nextind.get("status", None) == "success":
                form["number"] = nextind["number"]
            else:
                logger.error(f"Next in is not successfull: {nextind.get('message')}")
                return nextind

        if Individual.select().where(Individual.number == form["number"]).exists():
            return {
                "status": "error",
                "message": "Individual number already exists",
            }
        if form.get("certificate", None) is not None:
            if Individual.select().where(Individual.certificate == form["certificate"]).exists():
                return {
                    "status": "error",
                    "message": "Individual certificate already exists",
                }
        if breeding_id is not None and (refusal := _litter_number_refusal(form["number"], litter)):
            return refusal

        birth_date = form.get("birth_date", None)
        if birth_date is None:
            return {"status": "error", "message": "Birth date must be defined"}
        else:
            birth_date = validate_date(birth_date)

        try:
            individual = form_to_individual(form, user)
        except ValueError as exception:
            return {"status": "error", "message": f"{exception}"}
        # form_to_individual resolves the number again: a rabbit created (and voided) since the check above
        # would be updated in place, outside its litter's lock and the rules below.
        if individual.id is not None:
            return {"status": "error", "message": "Individual number already exists"}
        # A paper certificate on a new rabbit is a first certificate: the litter rules, under the litter lock
        # taken above, as on every other route that issues one.
        if individual.certificate and breeding_id is not None:
            try:
                validate_first_certificate(Breeding.get_by_id(breeding_id))
            except RosterAliveExceeds6w as exception:
                return {"status": "error", "message": f"{exception}", "must_mark_dead": exception.must_mark_dead}
            except ValueError as exception:
                return {"status": "error", "message": f"{exception}"}
        if "weights" in form:
            update_weights(individual, form["weights"], user.username)
        if "bodyfat" in form:
            update_bodyfat(individual, form["bodyfat"], user.username)

        individual.save()

        try:
            update_herdtracking_values(
                individual=individual,
                new_herd=individual.origin_herd,
                user_signature=user,
                tracking_date=birth_date,
                kind="BIRTH",
            )
        except ValueError as exception:
            # No Individual without its BIRTH row: undo the insert above, keep the legacy response.
            txn.rollback()
            return {"status": "error", "message": f"{exception}"}

        selling_date = form.get("selling_date", None)
        if selling_date is not None:
            selling_date = validate_date(selling_date)

        new_herd = herd
        if new_herd != individual.origin_herd:
            try:
                update_herdtracking_values(
                    individual=individual,
                    new_herd=new_herd,
                    user_signature=user,
                    tracking_date=datetime.utcnow() if not selling_date else selling_date,
                    kind="TRANSFER",
                )
            except ValueError as exception:
                raise exception

        logging.getLogger(f"{individual.current_herd.genebank.name}_create").info(
            f"{user.username},{individual.number},{individual.name},{new_herd.herd},{selling_date}"
        )
        return {
            "status": "success",
            "message": "Individual Created",
            "number": individual.number,
        }


def _litter_number_refusal(number, litter):
    """
    Legacy's minimal block: a number given for a litter must carry the litter's birth year
    and litter number; the choice between paper and Stamboken is made in v2. A litter without a litter number
    or birth date, or a number in another form, is checked for uniqueness only, as before.
    """
    parsed = parse_number(number)
    if litter is None or litter.birth_date is None or litter.litter_number is None or parsed is None:
        return None
    herd, year, litter_number, position = parsed
    if (year, litter_number) == (f"{litter.birth_date:%y}", litter.litter_number):
        return None
    right = f"{herd}-{litter.birth_date:%y}{litter.litter_number}{position}"
    return {"status": "error", "message": litter_mismatch(number, litter, right)}


def update_herdtracking_values(
    individual, new_herd, user_signature, tracking_date, kind, operation_id=None, notes=None
):
    """Legacy entry point, kept for its callers — delegates to the central writer."""
    return record_herd_tracking(individual, new_herd, tracking_date, kind, user_signature, operation_id, notes=notes)


# Legacy PATCH cannot carry a reason (ADR-0006): its admin genebank changes get this note.
LEGACY_GENEBANK_CHANGE_NOTE = "Genbanksbyte av admin via legacy"


@number_assets.finishing  # inside a caller's transaction, teardown_request finishes instead
def update_individual(form, user_uuid, issue_digital=False, genebank_change_reason=None, clear_nulls=False, buyer=None):
    """
    Updates the individual `form["id"]` by the values in `form`, if the user identified by `user_uuid`
    may: translate (utils.individual_legacy) turns the form into write commands, which execute runs under
    the lock, and their refusals become today's responses. `issue_digital` (the certificate routes only,
    never a request field) assigns the next digital certificate number. `genebank_change_reason` is the
    required note for an admin's move into another genebank (legacy PATCH passes
    LEGACY_GENEBANK_CHANGE_NOTE, the v2 certificate routes the body's reason; the legacy certificate
    routes pass none, and their form drops herd). `clear_nulls` (v2) clears the death and castration
    fields sent as null. `buyer` (v2) is the buyer outside the association on a sale to GX1/MX1.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}

    if not user.can_edit(form["id"]):
        return {"status": "error", "message": "Forbidden"}
    form.pop("new_individual", None)  # an update is never a creation
    if "breeding" in form:  # one canonical id for the lock set and the write
        try:
            form["breeding"] = canonical_breeding_id(form["breeding"])
        except ValueError as exception:
            return {"status": "error", "message": f"{exception}"}
    if Individual.get(Individual.id == form["id"]).voided:
        return {"status": "error", "message": "Individual not found"}
    try:
        individual = execute(
            user,
            form["id"],
            lambda ctx: translate(
                form,
                ctx,
                issue_digital=issue_digital,
                clear_nulls=clear_nulls,
                genebank_change_reason=genebank_change_reason,
                buyer=buyer,
            ),
            target_breeding=form.get("breeding"),
        )
    except IndividualRefused as exc:
        return exc.envelope
    except HerdTrackingError as exc:
        # The transaction has rolled back: no partial Individual write is committed.
        logger.warning(f"Rejected update of individual {form.get('id')}:{form.get('number')}: {exc.detail}")
        return {
            "status": "error",
            "message": exc.detail,
            "problem_status": exc.status,
            "title": exc.title,
            "rows": exc.rows,
        }
    except Exception as e:
        if hasattr(e, "individual_stage"):  # today's checks before the lock: legacy 500, v2 400/500
            raise
        logger.error(f"Expetion in update individual {form.get('id')}, user: {user.username} exception: {e}")
        return {"status": "error", "message": "Kunde inte uppdatera individ."}
    return {
        "status": "success",
        "message": "Individual Updated",
        "digital_certificate": individual.digital_certificate,
    }


def get_individuals(genebank_id, user_uuid=None):
    """
    Returns all individuals for a given `genebank_id` that the user identified
    by `user_uuid` has access to.
    """
    user = fetch_user_info(user_uuid)
    if user is None or genebank_id not in user.accessible_genebanks:
        return None  # not logged in
    try:
        # Holder row per individual (void-filtered, shared order) plus life-sign date
        current_herd = latest_ht_per_individual().alias("current_herd")
        # count children for individuals. This can be done in two ways - total
        # number of children, or number of children that is available in the
        # database.

        # total_children = Breeding.select(fn.SUM(Breeding.litter_size)) \
        #                          .where((Breeding.father == Individual.id) |
        #                                 (Breeding.mother == Individual.id))

        # pylint: disable=invalid-name
        Children = Individual.alias()
        children_in_db = (
            Children.select(fn.COUNT(Children.id))
            .join(Breeding)
            .where((Breeding.father == Individual.id) | (Breeding.mother == Individual.id))
            .where(not_voided(Children))
        )

        # use the children in the database for the result
        children = children_in_db

        # pylint: disable=invalid-name
        Father = Individual.alias()
        Mother = Individual.alias()
        # Join all the needed tables
        g_query = (
            Individual.select(
                Individual,
                Breeding,
                Color.id.alias("color_id"),
                Color.name.alias("color_name"),
                Father.id.alias("father_id"),
                Father.name.alias("father_name"),
                Father.number.alias("father_number"),
                Mother.id.alias("mother_id"),
                Mother.name.alias("mother_name"),
                Mother.number.alias("mother_number"),
                current_herd.c.life_sign_date,
                Herd.id.alias("herd_id"),
                Herd.herd,
                Herd.herd_name,
                Herd.is_active.alias("herd_active"),
                Genebank.name.alias("genebank_name"),
                children.alias("children"),
            )
            .join(Breeding)
            .join(Father, JOIN.LEFT_OUTER, on=(Father.id == Breeding.father_id))
            .join(Mother, JOIN.LEFT_OUTER, on=(Mother.id == Breeding.mother_id))
            .join(Color, JOIN.LEFT_OUTER, on=(Individual.color_id == Color.id))
            # No active row: fall back to the origin herd, like individual detail and the explorer.
            .join(
                current_herd,
                JOIN.LEFT_OUTER,
                on=((Individual.id == current_herd.c.i_id) & (current_herd.c.rank == 1)),
            )
            .join(Herd, on=(Herd.id == fn.COALESCE(current_herd.c.herd, Individual.origin_herd_id)))
            .join(Genebank, on=(Herd.genebank == Genebank.id))
            .where(Genebank.id == genebank_id)
            .where(not_voided())
        )

        # individuals are considered invalid if they have no life sign (spec
        # 999.5) newer than the active window.
        max_report_time = (datetime.now() - timedelta(days=ACTIVE_WINDOW_DAYS)).date()

        def as_date(value):
            """
            Function to coerce a value to datetime.date as sqlite returns
            string and postgresql returns datetime.
            """
            if isinstance(value, date):
                return value
            return datetime.strptime(value, "%Y-%m-%d").date()

        with DATABASE.atomic():
            # return as a list of certain fields
            return [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "certificate": (i["digital_certificate"] if i["certificate"] is None else i["certificate"]),
                    "digital_certificate": i["digital_certificate"],
                    "number": i["number"],
                    "sex": i["sex"],
                    "birth_date": (i["birth_date"].strftime("%Y-%m-%d") if i["birth_date"] else None),
                    "death_date": (i["death_date"].strftime("%Y-%m-%d") if i["death_date"] else None),
                    "death_note": i["death_note"],
                    "castration_date": i["castration_date"],
                    "litter_size": i["litter_size"],
                    "notes": i["notes"],
                    "color_note": i["color_note"],
                    "father": {
                        "id": i["father_id"],
                        "name": i["father_name"],
                        "number": i["father_number"],
                    },
                    "mother": {
                        "id": i["mother_id"],
                        "name": i["mother_name"],
                        "number": i["mother_number"],
                    },
                    "color": {"id": i["color_id"], "name": i["color_name"]},
                    "herd": {
                        "id": i["herd_id"],
                        "herd": i["herd"],
                        "herd_name": i["herd_name"],
                    },
                    "genebank": i["genebank_name"],
                    "herd_active": i["herd_active"],
                    "is_active": i["herd_active"]
                    and i["herd"] not in OUTSIDE_GENEBANK_HERDS
                    and (i["certificate"] or i["digital_certificate"])
                    and not i["death_date"]
                    and not i["death_note"]
                    and not i["castration_date"]
                    and i["life_sign_date"] is not None
                    and as_date(i["life_sign_date"]) > max_report_time,
                    "alive": i["death_date"] is None and not i["death_note"],
                    "children": i["children"],
                }
                for i in g_query.dicts()
            ]
    except DoesNotExist:
        return []


def _derive_individual_status(ind, max_report_time):
    """
    Derive individual status matching frontend IndividualCard.tsx getStatusInfo().
    Returns a lowercase English status string for API consumption.
    """
    note = (ind.get("death_note") or "").lower()
    is_escaped = any(w in note for w in ("rymt", "rymde", "försvann", "stulen"))
    is_slaughtered = ind.get("butchered") or any(w in note for w in ("slakt", "kött"))
    is_euthanized = "avliv" in note
    alive = ind.get("death_date") is None and not ind.get("death_note")

    if ind.get("death_date"):
        if is_slaughtered:
            return "slaktad"
        if is_euthanized:
            return "avlivad"
        return "död"

    if not alive and is_escaped:
        return "försvunnen"
    if not alive and is_slaughtered:
        return "slaktad"
    if not alive and is_euthanized:
        return "avlivad"
    if not alive:
        return "död"

    # Derive is_active (same logic as get_individuals)
    def as_date_val(value):
        if isinstance(value, date):
            return value
        if value is None:
            return None
        return datetime.strptime(str(value), "%Y-%m-%d").date()

    life_sign = as_date_val(ind.get("life_sign_date"))
    is_active = (
        ind.get("herd_active")
        and ind.get("herd") not in OUTSIDE_GENEBANK_HERDS
        and (ind.get("certificate") or ind.get("digital_certificate"))
        and not ind.get("castration_date")
        and life_sign is not None
        and life_sign > max_report_time
    )
    if not is_active:
        return "inactive"
    return "active"


def get_paginated_individuals(
    user_uuid,
    page=1,
    per_page=50,
    sort="name",
    order="asc",
    genebank_id=None,
    search=None,
    status=None,
    sex=None,
    herd_id=None,
    include_historical=False,
):
    """
    Returns paginated individuals with filtering, sorting, and search.
    For the Next.js Rabbit Explorer.
    """
    # Clamp per_page and page before any early returns so response metadata is always valid
    per_page = min(per_page, 200)
    if per_page < 1:
        per_page = 50
    if page < 1:
        page = 1

    user = fetch_user_info(user_uuid)
    if user is None:
        return None

    accessible = user.accessible_genebanks
    if not accessible:
        return {"items": [], "total_count": 0, "page": page, "per_page": per_page, "total_pages": 0}

    try:
        # Holder row per individual (DISTINCT ON, PostgreSQL) — void-filtered, in the herd-tracking order.
        current_herd = latest_ht_per_individual(distinct_on=True).alias("current_herd")

        # Core query: JOINs needed for filtering + access control.
        # LEFT OUTER JOINs ensure individuals without Breeding or HerdTracking
        # are still included — Individual.breeding is nullable and not all
        # rabbits have herd-tracking history.
        core_query = (
            Individual.select(
                Individual.id,
                Individual.name,
                Individual.number,
                Individual.sex,
                Individual.certificate,
                Individual.digital_certificate,
                Individual.death_date,
                Individual.death_note,
                Individual.is_active,
                Individual.has_photo,
                Individual.butchered,
                Individual.castration_date,
                Breeding.birth_date,
                current_herd.c.life_sign_date,
                Herd.herd,
                Herd.is_active.alias("herd_active"),
            )
            .join(Breeding, JOIN.LEFT_OUTER)
            .switch(Individual)
            .join(current_herd, JOIN.LEFT_OUTER, on=(Individual.id == current_herd.c.i_id))
            .join(
                Herd,
                on=(Herd.id == fn.COALESCE(current_herd.c.herd, Individual.origin_herd_id)),
            )
            .join(Genebank, on=(Herd.genebank == Genebank.id))
            .where(Genebank.id.in_(accessible))
            .where(not_voided())
        )

        # --- Filters (applied to core_query so count skips parent/color JOINs) ---

        # Genebank filter
        if genebank_id is not None:
            if genebank_id not in accessible:
                return {"items": [], "total_count": 0, "page": page, "per_page": per_page, "total_pages": 0}
            core_query = core_query.where(Genebank.id == genebank_id)

        # Search filter (partial, case-insensitive)
        if search:
            core_query = core_query.where(
                (fn.LOWER(Individual.name).contains(search.lower()))
                | (fn.LOWER(Individual.number).contains(search.lower()))
            )

        # Sex filter
        if sex:
            core_query = core_query.where(Individual.sex == sex)

        # Status filter
        max_report_time = (datetime.now() - timedelta(days=ACTIVE_WINDOW_DAYS)).date()

        if status:
            alive_cond = Individual.death_date.is_null() & (
                Individual.death_note.is_null() | (Individual.death_note == "")
            )
            not_alive_cond = Individual.death_date.is_null(False) | (
                Individual.death_note.is_null(False) & (Individual.death_note != "")
            )
            note_lower = fn.LOWER(fn.COALESCE(Individual.death_note, ""))

            # Truthy certificate: non-NULL and non-empty (matches Python truthiness)
            has_certificate = (
                Individual.certificate.is_null(False) & (Individual.certificate != "")
            ) | Individual.digital_certificate.is_null(False)

            # Shared death-note keyword conditions (used by multiple status branches)
            slaughtered = (
                (Individual.butchered == True)  # noqa: E712
                | note_lower.contains("slakt")
                | note_lower.contains("kött")
            )
            escaped = (
                note_lower.contains("rymt")
                | note_lower.contains("rymde")
                | note_lower.contains("försvann")
                | note_lower.contains("stulen")
            )
            euthanized = note_lower.contains("avliv")

            if status == "active":
                core_query = core_query.where(
                    alive_cond
                    & (Herd.is_active == True)  # noqa: E712
                    & has_certificate
                    & Individual.castration_date.is_null()
                    & Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS)
                    & (current_herd.c.life_sign_date > max_report_time)
                )
            elif status == "inactive":
                core_query = core_query.where(alive_cond)
                core_query = core_query.where(
                    (Herd.is_active == False)  # noqa: E712
                    | Herd.is_active.is_null()
                    | ~has_certificate
                    | Individual.castration_date.is_null(False)
                    | Herd.herd.in_(OUTSIDE_GENEBANK_HERDS)
                    | (current_herd.c.life_sign_date <= max_report_time)
                    | current_herd.c.life_sign_date.is_null()
                )
            elif status == "slaktad":
                core_query = core_query.where(
                    (Individual.death_date.is_null(False) & slaughtered)
                    | (Individual.death_date.is_null() & not_alive_cond & slaughtered & ~escaped)
                )
            elif status == "avlivad":
                core_query = core_query.where(
                    (Individual.death_date.is_null(False) & ~slaughtered & euthanized)
                    | (Individual.death_date.is_null() & not_alive_cond & euthanized & ~escaped & ~slaughtered)
                )
            elif status == "försvunnen":
                core_query = core_query.where(Individual.death_date.is_null() & not_alive_cond & escaped)
            elif status in ("dead", "död"):
                core_query = core_query.where(
                    (Individual.death_date.is_null(False) & ~slaughtered & ~euthanized)
                    | (Individual.death_date.is_null() & not_alive_cond & ~escaped & ~slaughtered & ~euthanized)
                )

        # Historical herd filter
        if herd_id and include_historical:
            try:
                target_herd = Herd.get(Herd.herd == herd_id)
                historical_ids = (
                    HerdTracking.select(HerdTracking.individual)
                    .where(HerdTracking.herd == target_herd.id, ht_not_voided())
                    .distinct()
                )
                core_query = core_query.where(Individual.id.in_(historical_ids))
            except DoesNotExist:
                pass

        # --- Full query: extend core with parent/color JOINs for response data ---
        Mother = Individual.alias()
        Father = Individual.alias()
        query = (
            core_query.select_extend(
                Breeding.litter_size,
                Breeding.litter_size6w,
                Color.name.alias("color_name"),
                Mother.number.alias("mother_number"),
                Mother.name.alias("mother_name"),
                Father.number.alias("father_number"),
                Father.name.alias("father_name"),
            )
            .switch(Breeding)
            .join(Mother, JOIN.LEFT_OUTER, on=(Breeding.mother == Mother.id))
            .switch(Breeding)
            .join(Father, JOIN.LEFT_OUTER, on=(Breeding.father == Father.id))
            .switch(Individual)
            .join(Color, JOIN.LEFT_OUTER, on=(Individual.color_id == Color.id))
        )

        # Sorting (with deterministic tiebreaker to prevent page drift)
        # TRIM + Swedish collation: ignore leading spaces, Å/Ä/Ö sort after Z
        name_sort = fn.TRIM(Individual.name).collate('"sv-SE-x-icu"')
        sort_columns = {
            "name": name_sort,
            "birth_date": Breeding.birth_date,
            "number": Individual.number,
        }
        sort_col = sort_columns.get(sort, name_sort)
        if order == "desc":
            sort_col = sort_col.desc()

        # When herd_id is specified, sort own-herd individuals first
        if herd_id:
            herd_priority = Case(Herd.herd, [(herd_id, Value(0))], Value(1))
            query = query.order_by(herd_priority, sort_col, Individual.id)
        else:
            query = query.order_by(sort_col, Individual.id)

        with DATABASE.atomic():
            total_count = core_query.count()
            total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0

            items = []
            for i in query.paginate(page, per_page).dicts():
                status_val = _derive_individual_status(i, max_report_time)
                items.append(
                    {
                        "number": i["number"],
                        "name": i["name"].strip() if i["name"] else None,
                        "sex": i["sex"],
                        "birth_date": i["birth_date"].strftime("%Y-%m-%d") if i["birth_date"] else None,
                        "status": status_val,
                        "herd": i["herd"],
                        "color": i["color_name"],
                        "has_photo": bool(i["has_photo"]),
                        "litter_size": i.get("litter_size"),
                        "litter_size6w": i.get("litter_size6w"),
                        "mother_number": i.get("mother_number"),
                        "mother_name": i.get("mother_name"),
                        "father_number": i.get("father_number"),
                        "father_name": i.get("father_name"),
                    }
                )

            return {
                "items": items,
                "total_count": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            }
    except DoesNotExist:
        return {"items": [], "total_count": 0, "page": page, "per_page": per_page, "total_pages": 0}


def get_all_genebanks():
    """
    Returns a list of all genebanks.
    """
    query = Genebank().select()

    # Using a list comprehension here will turn the iterator into a list
    return [g for g in query.execute()]  # pylint: disable=unnecessary-comprehension


def get_all_individuals():
    """
    Returns the neccessary information about all individuals for computing genetic coefficients.

    :return: A list of dictionaries containing genetic features of the individuals
    :rtype: list(dict)
    """
    try:
        individuals_dict = []
        with DATABASE.atomic():
            for data in Individual.select(Individual, Breeding).join(Breeding).where(not_voided()).dicts():
                ind = dict()
                ind["id"] = str(data["id"])
                ind["father"] = str(data["father"]) if (data["father"] and data["mother"]) else "0"
                ind["mother"] = str(data["mother"]) if (data["mother"] and data["father"]) else "0"
                ind["sex"] = "M" if data["sex"] == "male" else "F"
                ind["phenotype"] = str(data["color"]) if data["color"] else "0"
                individuals_dict.append(ind)
            return individuals_dict
    except DoesNotExist:
        return []


# Breeding and birth functions


def get_breeding_event(breed_id, user_uuid):
    """
    Returns a list of all breeding events given by `herd_id`.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return []

    try:
        with DATABASE.atomic():
            breed = Breeding.select().where(Breeding.id == breed_id).get().as_dict()
            herd = Herd.get(Herd.herd == breed["breeding_herd"])

            if herd.genebank.id not in user.accessible_genebanks:
                return []

            return breed
    except DoesNotExist:
        logging.warning("Unknown herd %s", breed_id)

    return []


def get_breeding_events(herd_id, user_uuid):
    """
    Returns a list of all breeding events given by `herd_id`.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return []

    try:
        herd = Herd.get(Herd.herd == herd_id)
        if herd.genebank.id not in user.accessible_genebanks:
            return []

        with DATABASE.atomic():
            query = Breeding.select().where(Breeding.breeding_herd_id == herd)
            return [b.as_dict() for b in query.iterator()]
    except DoesNotExist:
        logger.warning("Unknown herd %s", herd_id)

    return []


def get_breeding_events_with_ind(herd_id, user_uuid):
    """
    Returns a list of all breeding events given by `herd_id`
    and all individuals with the same breeding id.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return []
    try:
        herd = Herd.get(Herd.herd == herd_id)
        if herd.genebank.id not in user.accessible_genebanks:
            return []
        breedings_dict = []
        with DATABASE.atomic():
            for breedings in Breeding.select().where(Breeding.breeding_herd_id == herd):
                individuals_dict = []
                for data in (
                    Individual.select(
                        Individual.number,
                        Individual.name,
                        Individual.color,
                        Individual.sex,
                        Individual.id,
                        Individual.origin_herd,
                        Individual.certificate,
                        Individual.digital_certificate,
                    )
                    .where(Individual.breeding_id == breedings.id)
                    .where(not_voided())
                    .order_by(Individual.number)
                ):
                    ind = dict()
                    if data:
                        ind["number"] = data.number
                        ind["name"] = data.name
                        ind["sex"] = data.sex
                        ind["color"] = data.color.name if data.color else None
                        ind["current_herd"] = data.current_herd.herd
                        ind["is_registered"] = True if data.certificate or data.digital_certificate else False
                    individuals_dict.append(ind)
                b = breedings.as_dict()
                b["individuals"] = individuals_dict
                breedings_dict.append(b)

            return breedings_dict

    except DatabaseError as exception:
        logger.error("Database error: %s", exception)
    # except DoesNotExist:
    #     logger.warning("Unknown herd %s", herd_id)

    return []


def get_breeding_events_by_date(birth_date, user_uuid):
    """
    Returns breeding events with `birth_date` in genebanks the user can access.
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return []

    try:
        with DATABASE.atomic():
            query = (
                Breeding.select()
                .join(Herd, on=(Breeding.breeding_herd_id == Herd.id))
                .where(Breeding.birth_date == birth_date)
                .where(Herd.genebank.in_(user.accessible_genebanks))
            )
            return [b.as_dict() for b in query.iterator()]
    except DatabaseError as exception:
        logger.error("Database error: %s", exception)

    return []


def register_breeding(form, user_uuid):
    """
    Registers a breeding event between two rabbits, defined by `form`, into the
    database (if the given `user` has sufficient permissions).

    The form should be formatted like:
    {
        mother: <individual-number>,
        father: <individual-number>,
        breeding_herd: <herd-number>,
        date: <breeding-date, as %Y-%m-%d>,
        notes: <text>,
    }

    The response will be on the format:
    JSON:  {
            status: 'success' | 'error',
            message?: string
           }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}

    errors = []
    try:
        with DATABASE.atomic():
            herd = Herd.get(Herd.herd == form.get("breeding_herd", None))
    except DoesNotExist:
        errors += ["Unknown herd"]
    # Check if the parents are valid
    try:
        mother = Individual.get(Individual.number == form.get("mother", None))
    except DoesNotExist:
        errors += ["Unknown mother"]
    try:
        father = Individual.get(Individual.number == form.get("father", None))
    except DoesNotExist:
        errors += ["Unknown father"]

    if errors:
        return {"status": "error", "message": ", ".join(errors)}

    # A user can insert a breeding event if they have permission to edit the
    # current herd.
    if not (user.can_edit(herd.herd)):
        return {"status": "error", "message": "Forbidden"}

    # check if the breeding date is valid
    try:
        breed_date = validate_date(form.get("date", None))
    except ValueError as error:
        return {"status": "error", "message": str(error)}

    # LOCK the parents first (ascending) and hold them through the insert: a seller's
    # undo-sale locks the doe and then checks for dependent breedings, so ownership must be decided under the same lock.
    with DATABASE.atomic():
        lock_individuals([mother.id, father.id])
        mother, father = Individual.get_by_id(mother.id), Individual.get_by_id(father.id)
        # An unpromoted (voided) rabbit cannot become a parent; decided under the lock unpromote takes.
        if mother.voided or father.voided:
            return {"status": "error", "message": "Unknown mother" if mother.voided else "Unknown father"}
        # Ownership check: the mother must be in the breeding herd now or have been
        # there at breed_date (Story 2.7, relaxed for the bought-pregnant case).
        # Admins and managers of the breeding herd's genebank bypass this check
        if not user.is_admin and herd.genebank_id not in (user.is_manager or []):
            if not mother_belongs_to_herd(mother, herd.id, breed_date):
                return {"status": "error", "message": "Honan tillhörde inte din besättning vid det angivna datumet"}

        # Check for duplicate breeding (existing behavior — must run before new validations)
        exists = (
            Breeding.select()
            .where(Breeding.father == father)
            .where(Breeding.mother == mother)
            .where(Breeding.breed_date == breed_date)
            .count()
        )
        if exists:
            return {"status": "error", "message": "Breeding already registered"}

        # Validate breeding date constraints
        date_errors, date_warnings = validate_breeding_dates(breed_date=breed_date, mother=mother, father=father)
        if date_errors:
            return {"status": "error", "message": " ".join(date_errors)}

        breeding = Breeding(
            father=father,
            mother=mother,
            breed_date=breed_date,
            breeding_herd_id=herd,
            breed_notes=form.get("notes", None),
        )
        breeding.save()
        logger.info(f"User:{user.username} added breeding: {breeding.as_dict()}")
        result = {"status": "success", "breeding_id": breeding.id}
        if date_warnings:
            result["warnings"] = date_warnings
        return result


def delete_breeding(id, user_uuid):
    """
    Delete an empty breeding with `id` (if the
    given `user` has sufficient permissions).

    The response will be on the format:
    JSON:  {
            status: 'success' | 'error',
            message?: string
           }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {
            "status": "error",
            "message": "Du är inte inloggad. Logga in och försök igen",
        }

    try:
        breeding = Breeding.get(id)
    except (DoesNotExist, KeyError):
        return {
            "status": "error",
            "message": f"Kan inte hitta parningen med id {id} i databasen",
        }

    # Auth anchored to the breeding's herd — null-safe (breeding_herd_id is always set).
    if not (user.can_edit(breeding.breeding_herd_id.herd)):
        return {"status": "error", "message": "Du har inte rätt behörighet"}

    try:
        with DATABASE.atomic():
            # LOCK ORDER: Breeding first, then Bunny — the same order v2
            # promotion takes (bunny_v2.py:93/328, individual_v2_create.py:99/274).
            # Taking it the other way round deadlocks against a promotion that
            # already holds the Breeding row and is about to write its Bunny.
            # This must stay the FIRST statement inside the transaction, before
            # the individuals check, so the check reads state nobody can change
            # under us.
            breeding = Breeding.select().where(Breeding.id == id).for_update().get()

            # check if the breeding has any registered individuals
            individuals = Individual.select(Individual.number).where(Individual.breeding_id == breeding.id).count()
            if individuals > 0:
                return {
                    "status": "error",
                    "message": f"Parningstillfället innehåller {individuals} individer \
                kan ej ta bort! prova att uppdatera sidan.",
                }

            # Unpromoted Bunny roster rows go with the litter. Legacy shows its
            # delete button exactly when the litter has no individuals and
            # cannot see roster rows, so refusing here would break the flow;
            # the individuals check above already returned for promoted kits.
            bunny_count = Bunny.delete().where(Bunny.breeding == breeding).execute()
            if bunny_count:
                logger.info(f"User:{user.username} deleted {bunny_count} bunny roster rows with breeding {id}")
            Breeding.delete().where(Breeding.id == id).execute()
            logger.info(f"User:{user.username} deleted empty breeding: {breeding.as_dict()}")
            return {"status": "success"}
    except DoesNotExist:
        return {
            "status": "error",
            "message": f"Kan inte hitta parningen med id {id} i databasen",
        }


def register_birth(form, user_uuid):
    """
    Updates a breeding event with birth information, defined by `form` (if the
    given `user` has sufficient permissions).

    The form should be formatted like:
    {
        id: <breeding database id>
        date: <birth-date, as %Y-%m-%d>,
        litter_size: <total litter size (including stillborn)>
        litter_size6w: <number of litter alive 6 weeks after birth, can be null>
        notes: <text>,
    }

    The response will be on the format:
    JSON:  {
            status: 'success' | 'error',
            message?: string
           }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}

    try:
        breeding = Breeding.get(form.get("id", None))
    except (DoesNotExist, KeyError):
        return {"status": "error", "message": "Breeding does not exist"}

    # Permission check: admins and managers bypass ownership validation (AC5)
    if not user.is_admin:
        if user.is_manager and breeding.breeding_herd_id.genebank_id in user.is_manager:
            pass  # Manager of this genebank — bypass temporal check
        elif user.is_owner:
            pass  # Owner — temporal check deferred until birth_date is parsed
        else:
            return {"status": "error", "message": "Forbidden"}

    errors = []
    date_warnings = []
    birth_date = None
    # check if the birth date is valid
    try:
        birth_date = validate_date(form.get("date", None))
    except ValueError as error:
        errors += [str(error)]

    # Ownership check: the mother must be in one of the user's herds now or have
    # been there at birth_date (Story 2.7, relaxed for the bought-pregnant case).
    # Re-run under the parent locks below. Only a manager of THIS litter's genebank skips it.
    manages_here = breeding.breeding_herd_id.genebank_id in (user.is_manager or [])
    owner_checked = not user.is_admin and not manages_here and user.is_owner and birth_date

    def _mother_in_user_herd(mother):
        return any(mother_belongs_to_herd(mother, Herd.get(Herd.herd == h).id, birth_date) for h in user.is_owner)

    not_owned = "Honan tillhörde inte din besättning vid det angivna datumet"
    if owner_checked and not _mother_in_user_herd(breeding.mother):
        errors += [not_owned]

    # check if the litter_size size is valid
    try:
        litter_size = int(form.get("litter_size", None))
        if litter_size <= 0:
            errors += ["Litter size must be larger than zero."]
        elif form.get("litter_size6w") is not None and int(form["litter_size6w"]) > litter_size:
            errors += [LITTER_SIZE6W_ABOVE_BORN]
    except ValueError:
        errors += ["Unknown litter size."]
    except TypeError:
        errors += ["Missing litter size."]

    if breeding.birth_date or breeding.birth_notes:
        errors += ["Birth already registered."]

    # Validate birth date constraints (only if no prior parsing errors)
    if birth_date and not errors:
        date_errors, date_warnings = validate_breeding_dates(
            breed_date=breeding.breed_date,
            birth_date=birth_date,
            mother=breeding.mother,
            father=breeding.father,
            exclude_breeding_id=breeding.id,
            litter_size=litter_size,
        )
        errors += date_errors

    if errors:
        return {"status": "error", "message": ", ".join(errors)}

    # Assign the stored Breeding.litter_number at birth registration. The mint helper only
    # backfills existing litters in the migration; a brand-new litter would stay
    # NULL and be unpromotable (create/promote require a non-null litter_number).
    # suggest_litter_number gives the chronological position; when that collides
    # with a later litter (an out-of-order birth) we append at the end so the birth
    # still registers, and surface the conflict for an explicit renumber.
    #
    # Fix 1: compute AND save the litter_number INSIDE the transaction, after taking a
    # FOR UPDATE over this herd/year's Breeding rows (mirroring renumber_litters), so
    # two concurrent register_birth for the same herd/year are serialised and can't
    # compute the same number → collide on idx_breeding_herd_year_litter (→ 500).
    birth_date_only = birth_date.date() if isinstance(birth_date, datetime) else birth_date
    herd_identifier = breeding.breeding_herd_id.herd

    def _max_litter_number() -> int:
        existing_numbers = [
            b.litter_number
            for b in Breeding.select(Breeding.litter_number).where(
                (Breeding.breeding_herd_id == breeding.breeding_herd_id)
                & (Breeding.id != breeding.id)
                & (Breeding.litter_number.is_null(False))
                & (
                    DATABASE.extract_date("year", fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30))
                    == birth_date_only.year
                )
            )
        ]
        return max(existing_numbers) if existing_numbers else 0

    with DATABASE.atomic():
        # Serialise the herd/year litter-number space before reading it,
        # deterministic order to avoid deadlocks — mirrors renumber_litters.
        # This litter is in the same ascending lock call even when its breed date falls in another year.
        list(
            Breeding.select()
            .where(
                (
                    (Breeding.breeding_herd_id == breeding.breeding_herd_id)
                    & (
                        DATABASE.extract_date("year", fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30))
                        == birth_date_only.year
                    )
                )
                | (Breeding.id == breeding.id)
            )
            .order_by(Breeding.id)
            .for_update()
        )
        # Then both parents in ONE ascending call, re-read, and the ownership check again:
        # a seller's undo-sale locks the doe and checks for a dependent birth.
        locked = Breeding.get_by_id(breeding.id)
        # Everything above was decided on the unlocked read: authority (the litter's genebank), the date rules
        # (mating and parents) and that no birth is registered. If any of it changed before the lock, refuse
        # instead of deciding on stale data; below, only the birth columns of the locked row are written.
        decided_on = ("breeding_herd_id_id", "mother_id", "father_id", "breed_date", "birth_date", "birth_notes")
        if any(getattr(locked, field) != getattr(breeding, field) for field in decided_on):
            return {"status": "error", "message": "Kullen ändrades samtidigt. Försök igen."}
        lock_individuals([p for p in (locked.mother_id, locked.father_id) if p is not None])
        if owner_checked and not _mother_in_user_herd(
            Individual.get_by_id(locked.mother_id) if locked.mother_id else None
        ):
            return {"status": "error", "message": not_owned}

        suggestion = suggest_litter_number(herd_identifier, birth_date_only, exclude_breeding_id=breeding.id)
        litter_conflicts = suggestion["conflicts"]
        assigned_litter_number = (_max_litter_number() + 1) if litter_conflicts else suggestion["suggested"]

        breeding = locked
        birth_columns = [
            Breeding.birth_date,
            Breeding.litter_size,
            Breeding.litter_size6w,
            Breeding.birth_notes,
            Breeding.litter_number,
            Breeding.updated_at,
        ]
        breeding.birth_date = birth_date
        breeding.litter_size = litter_size
        breeding.litter_size6w = form.get("litter_size6w", None)
        breeding.birth_notes = form.get("notes", None)
        breeding.litter_number = assigned_litter_number
        try:
            with DATABASE.atomic():  # savepoint
                breeding.save(only=birth_columns)
        except IntegrityError:
            # Secondary guard: a herd/year with no pre-existing dated sibling can't be
            # serialised by the FOR UPDATE above, so a simultaneous first birth may have
            # claimed our number. Append max+1 and retry, surfacing it as a conflict.
            assigned_litter_number = _max_litter_number() + 1
            breeding.litter_number = assigned_litter_number
            breeding.save(only=birth_columns)
            litter_conflicts = litter_conflicts or [{"reason": "litter_number_taken"}]

        # Seed the roster with one row per kit born so the list matches the
        # reported litter size; only when the litter has no rows yet, so a
        # re-registered birth never duplicates manually managed rows.
        if litter_size and not Bunny.select().where(Bunny.breeding == breeding).exists():
            for slot in range(1, litter_size + 1):
                Bunny.create(breeding=breeding, slot_order=slot)

        logger.info(f"User:{user.username} added birth: {breeding.as_dict()}")
        result = {"status": "success", "litter_number": assigned_litter_number}
        if litter_conflicts:
            result["litter_number_conflicts"] = litter_conflicts
        if date_warnings:
            result["warnings"] = date_warnings
        return result


@number_assets.finishing
def update_breeding(form, user_uuid):
    """
    Updates a breeding event with the information in `form` (if the
    given `user` has sufficient permissions).

    The form should be formatted like:
    {
        id: <breeding database id>
        breeding_herd: <herdnumber>
        breed_date?: <date, as %Y-%m-%d>,
        breed_notes?: string,
        father?: <individual-number>,
        mother?: <individual-number>,
        birth_date?: <date, as %Y-%m-%d>,
        birth_notes?: string,
        litter_size?: <total litter size (including stillborn)>,
        litter_size6w: <number of litter alive 6 weeks after birth, can be null>
    }

    The response will be on the format:
    JSON:  {
            status: 'success' | 'error',
            message?: string
           }
    """
    user = fetch_user_info(user_uuid)
    if user is None:
        return {"status": "error", "message": "Not logged in"}

    try:
        breeding = Breeding.get(form["id"])
    except (DoesNotExist, KeyError):
        return {"status": "error", "message": "Breeding does not exist"}

    # Authority is the litter's own herd (as in delete_breeding), not holding a parent: a date or
    # parent change rewrites every kit's BIRTH row and number. Re-checked under the lock below.
    if not user.can_edit(breeding.breeding_herd_id.herd):
        return {"status": "error", "message": "Forbidden"}
    update_logger = logging.getLogger(f"{breeding.mother.current_herd.genebank.name}_update")
    errors = []
    date_warnings = []
    # `breeding` is the row as this request found it, read before the lock. Legacy PATCHes the
    # WHOLE breeding object, unchanged fields included, so a field counts as changed only when
    # the form differs from that read. Only those changes are applied to the row re-read under
    # the lock: an echoed value cannot revert a correction committed in between. A no-op
    # echo (or a notes-only edit) does not re-validate the row's existing state either; only a
    # change to breed_date, birth_date, mother, father or litter_size triggers validation.
    changes = {}
    # Check if the parents are valid
    if "mother" in form:
        try:
            old_mother = breeding.mother.number
            mother = Individual.get(Individual.number == form["mother"])
            if old_mother != mother.number:
                changes["mother"] = mother
                update_logger.info(
                    f"{user.username},breeding_id:{breeding.id},changed_mother,{old_mother},{mother.number}"
                )
        except DoesNotExist:
            errors += ["Unknown mother"]
    if "father" in form:
        try:
            old_father = breeding.father.number
            father = Individual.get(Individual.number == form["father"])
            if old_father != father.number:
                changes["father"] = father
                update_logger.info(
                    f"{user.username},breeding_id:{breeding.id},changed_father,{old_father},{father.number}"
                )
        except DoesNotExist:
            errors += ["Unknown father"]

    for bdate in ["breed_date", "birth_date"]:
        if bdate in form:
            try:
                new_date = validate_date(form[bdate])
                if getattr(breeding, bdate) != new_date.date():
                    update_logger.info(
                        f"{user.username},breeding_id:{breeding.id},changed_{bdate},{getattr(breeding, bdate)},{form[bdate]}"  # noqa: E501
                    )
                    changes[bdate] = new_date
            except ValueError as error:
                errors += [str(error)]

    stored_sizes = (breeding.litter_size, breeding.litter_size6w)
    # check if the litter_size is valid (null keeps the stored value: v2 sends it for a pending mating)
    if form.get("litter_size") is not None:
        try:
            new_litter_size = int(form["litter_size"])
            if new_litter_size != breeding.litter_size:
                changes["litter_size"] = new_litter_size
            if new_litter_size <= 0:
                errors += ["Litter size must be larger than zero."]
        except (TypeError, ValueError):
            errors += ["Unknown litter size."]
    # Alive at 6 weeks cannot exceed born (once the rest is valid). Checked only when either changes:
    # legacy echoes the whole row, and an old row that breaks the rule must still save its other edits.
    try:
        new_litter_size6w = form.get("litter_size6w", breeding.litter_size6w)
        new_sizes = (
            changes.get("litter_size", breeding.litter_size),
            None if new_litter_size6w is None else int(new_litter_size6w),
        )
        if not errors and new_sizes != stored_sizes and None not in new_sizes and new_sizes[1] > new_sizes[0]:
            errors += [LITTER_SIZE6W_ABOVE_BORN]
        # Compared as an int: a string echo ("3") of the read value is no change and must not revert
        # a correction committed before the lock.
        if new_sizes[1] != breeding.litter_size6w:
            changes["litter_size6w"] = new_sizes[1]
    except (TypeError, ValueError):
        errors += ["Unknown litter size."]

    for field in ("birth_notes", "breed_notes"):
        if field in form and form[field] != getattr(breeding, field):
            changes[field] = form[field]

    if errors:
        return {"status": "error", "message": ", ".join(errors)}

    parents_changed = "mother" in changes or "father" in changes
    validation_input_changed = bool(changes.keys() & {"mother", "father", "breed_date", "birth_date", "litter_size"})
    # The BIRTH rows move below, in the same transaction as the breeding save.
    new_birth_date = changes.get("birth_date")

    # Birth-row replacements, kit origin changes and the breeding save are ONE transaction: a
    # refused sibling (HerdTrackingError) must leave every kit and the breeding untouched.
    try:
        with DATABASE.atomic():
            # LOCK ORDER: Breeding first, then individuals in ascending id in ONE call — the order
            # delete_breeding and set_litter_number/renumber_litters take.
            stored = Breeding.select().where(Breeding.id == breeding.id).for_update().get()
            # Authorize again under the lock: the pre-check above read an unlocked herd.
            if not user.can_edit(stored.breeding_herd_id.herd):
                return {"status": "error", "message": "Forbidden"}
            kits = Individual.select().where(Individual.breeding_id == breeding.id).order_by(Individual.id)
            new_herd = Herd.get(Herd.herd == form["breeding_herd"]) if "breeding_herd" in form else None
            # A move only when the form differs from this request's read (legacy echoes the herd) and the row.
            herd_changed = new_herd is not None and new_herd not in (breeding.breeding_herd_id, stored.breeding_herd_id)
            # Moving the litter rewrites every kit's origin, number and BIRTH row: the same rule as an
            # individual's origin_herd change. Within the genebank admins and its managers; into another
            # genebank an admin correction only, decided here: a kit sold on keeps its holder, so the
            # herd-tracking checks downstream see no genebank change.
            stored_genebank = stored.breeding_herd_id.genebank_id
            if herd_changed and not (
                user.is_admin
                or (new_herd.genebank_id == stored_genebank and stored_genebank in (user.is_manager or []))
            ):
                return {"status": "error", "message": "Forbidden"}
            # Parents and birth date are part of a registered kit's identity: the same manager-only rule as
            # MoveToLitter (CERT_GUARDED) for a certified rabbit, so the litter is no way around it.
            if (
                changes.keys() & {"mother", "father", "birth_date"}
                and not is_manager_of(user, stored_genebank)
                and kits.clone()
                .where(Individual.certificate.is_null(False) | Individual.digital_certificate.is_null(False))
                .exists()
            ):
                return {
                    "status": "error",
                    "message": (
                        "Bara genbanksansvarig kan ändra föräldrar eller födelsedatum"
                        " på en kull med registrerade ungar."
                    ),
                    "problem_status": 403,
                    "title": "Forbidden",
                }
            # Kit writes need the kit locks. The stored parents and any new parents (validated
            # below) are locked too, so a concurrent undo-sale serialises with us.
            kit_writes = new_birth_date is not None or herd_changed
            locked = [kit.id for kit in kits.clone().select(Individual.id)] if kit_writes else []
            stored_parents = [p for p in (stored.mother_id, stored.father_id) if p is not None]
            locked += stored_parents
            if parents_changed:
                locked += [changes[role].id for role in ("mother", "father") if role in changes]
            lock_individuals(locked)
            # This request's changes go onto the locked row; everything else stays as committed.
            for field, value in changes.items():
                setattr(stored, field, value)
            # Alive at 6 weeks ≤ born again on the locked row: the other size may have been corrected
            # since this request's read (certificates count against litter_size6w).
            locked_sizes = (stored.litter_size, stored.litter_size6w)
            if new_sizes != stored_sizes and None not in locked_sizes and locked_sizes[1] > locked_sizes[0]:
                return {"status": "error", "message": LITTER_SIZE6W_ABOVE_BORN}
            if parents_changed:  # re-read under the lock
                stored.mother = Individual.get_or_none(Individual.id == stored.mother_id)
                stored.father = Individual.get_or_none(Individual.id == stored.father_id)
                # A new parent must not be an unpromoted (voided) rabbit; decided under its lock.
                for role in ("mother", "father"):
                    parent = getattr(stored, role)
                    if role in changes and parent is not None and parent.voided:
                        errors += [f"Unknown {role}"]
            # Validate the resulting row, but only when the form actually changed one of the
            # validated fields (see the comment above `changes`).
            if not errors and validation_input_changed:
                # Identity and sex are never downgraded — the same individual as both
                # parents, or a parent in a role its sex contradicts, is a broken edit
                # for every role, not a historical-data artefact.
                errors += validate_parent_roles(stored.mother, stored.father)
                date_errors, date_warnings = validate_breeding_dates(
                    breed_date=stored.breed_date,
                    birth_date=stored.birth_date,
                    mother=stored.mother,
                    father=stored.father,
                    exclude_breeding_id=stored.id,
                    litter_size=stored.litter_size,
                    include_parent_roles=False,
                )
                if date_errors and (
                    user.is_admin or (user.is_manager and stored.breeding_herd_id.genebank_id in user.is_manager)
                ):
                    # Admins and genebank managers may correct historical rows that no
                    # longer satisfy today's rules — same bypass as register_breeding.
                    date_warnings += date_errors
                else:
                    errors += date_errors
            if errors:
                return {"status": "error", "message": ", ".join(errors)}
            # Under the litter + parent locks, before any write: no kit may become its own ancestor.
            # After the validation errors, so an existing refusal keeps its message.
            if parents_changed:
                kit_ids = [kit.id for kit in kits.clone().select(Individual.id)]
                if pedigree_cycle_error(kit_ids, stored.father_id, stored.mother_id):
                    return dict(CYCLE_PROBLEM)
            if new_birth_date is not None:
                for ind in kits.clone():  # read after the lock
                    logger.info(f"Indi: {ind.number} birth: {ind.breeding.birth_date}")
                    update_birth_date_herd_tracking(
                        ind, user, new_date=new_birth_date, old_date=ind.breeding.birth_date
                    )

            # Check if breeding_herd has changed
            # Update breeding_herd to new herd ID.
            # Update all Indivuduals in breeding
            if herd_changed:
                update_logger.info(
                    f"{user.username},breeding_id:{breeding.id},new_breeding_herd,{stored.breeding_herd_id.herd},{new_herd.herd}"  # noqa: E501
                )
                stored.breeding_herd_id = new_herd
                # Breeding herd id changed
                for ind in kits.clone():
                    update_origin_herd_ind(ind, new_herd, user)

            stored.save()
    except HerdTrackingError as exc:
        logger.warning(f"Rejected update of breeding {breeding.id}: {exc.detail}")
        return {
            "status": "error",
            "message": exc.detail,
            "problem_status": exc.status,
            "title": exc.title,
            "rows": exc.rows,
        }
    except number_assets.AssetMoveError as exc:  # rolled back; legacy keeps its 200 error envelope
        logger.error(f"Breeding {breeding.id} not updated, a kit's certificate/photo could not follow: {exc}")
        return {"status": "error", "message": "Intyg eller foto kunde inte flyttas till det nya numret."}
    result = {"status": "success"}
    if date_warnings:
        result["warnings"] = date_warnings
    return result


def create_yearly_report_round(form, user_uuid=None):
    """
    Creates a new YearlyReportRound based on the form data.
    Only accessible to admin or manager users.
    """
    user = fetch_user_info(user_uuid)
    if not user or not (user.is_admin or user.is_manager):
        return {"status": "error", "message": "Forbidden"}
    try:
        new_round = YearlyReportRound.create(
            report_year=form.get("report_year"),
            start_date=form.get("start_date"),
            end_date=form.get("end_date"),
            is_active=form.get("is_active", False),
            created_by=user,
            # creation_date is set automatically
        )
        return {"status": "success", "round": new_round.id}
    except Exception as e:
        # ...existing error handling...
        return {"status": "error", "message": str(e)}


def update_yearly_report_round(round_id, form, user_uuid):
    """
    Updates an existing YearlyReportRound with data from the form.
    Only accessible to admin or manager users.
    """
    user = fetch_user_info(user_uuid)
    if not (user.is_admin or user.is_manager):
        return {"status": "error", "message": "Forbidden"}
    try:
        yr_round = YearlyReportRound.get(YearlyReportRound.id == round_id)
        yr_round.start_date = form.get("start_date", yr_round.start_date)
        yr_round.end_date = form.get("end_date", yr_round.end_date)
        yr_round.is_active = form.get("is_active", yr_round.is_active)
        yr_round.manually_activated = form.get("manually_activated", yr_round.manually_activated)
        yr_round.report_year = form.get("report_year", yr_round.report_year)
        # Do not update 'created_by' or 'creation_date'
        yr_round.save()
        return {"status": "success", "round": yr_round.id}
    except YearlyReportRound.DoesNotExist:
        return {"status": "error", "message": "YearlyReportRound not found."}
    except Exception as e:
        # ...existing error handling...
        return {"status": "error", "message": str(e)}


def get_yearly_report_rounds_with_counts(user_uuid=None):
    """
    Retrieves all YearlyReportRounds along with the count of submitted YearlyHerdReports per round.
    Accessible to all users.
    """
    _user = fetch_user_info(user_uuid)
    try:
        rounds_query = (
            YearlyReportRound.select(
                YearlyReportRound,
                fn.COUNT(YearlyHerdReport.id).alias("report_count"),
                User.username.alias("created_by_username"),
            )
            .join(User, on=(YearlyReportRound.created_by == User.id))
            .switch(YearlyReportRound)
            .join(
                YearlyHerdReport,
                JOIN.LEFT_OUTER,
                on=(YearlyHerdReport.round == YearlyReportRound.id),
            )
            .group_by(YearlyReportRound, User.username)
            .dicts()
        )
        rounds = list(rounds_query)
        return rounds
    except Exception as e:
        logger.error(f"Error retrieving yearly report rounds: {e}")
        return []  # Return an empty list in case of error


def delete_yearly_report_round(round_id, user_uuid=None):
    """
    Deletes a YearlyReportRound entry if the user has the required permissions.
    """
    user = fetch_user_info(user_uuid)
    if not user or not (user.is_admin or user.is_manager):
        return {"status": "error", "message": "Unauthorized"}

    try:
        round_entry = YearlyReportRound.get_by_id(round_id)
        round_entry.delete_instance()
        return {"status": "success", "message": "Yearly report round deleted"}
    except YearlyReportRound.DoesNotExist:
        return {"status": "error", "message": "Yearly report round not found"}
    except Exception as e:
        logger.error(f"Error deleting yearly report round: {e}")
        return {
            "status": "error",
            "message": "An error occurred while deleting the round",
        }


def get_yearly_report_by_round(herd_id, round_id):
    try:
        report = (
            YearlyHerdReport.select()
            .where((YearlyHerdReport.herd == herd_id) & (YearlyHerdReport.round == round_id))
            .get()
        )
        report_data = report.as_dict()
        # Parse the JSON data field
        report_data["data"] = json.loads(report_data["data"])
        return report_data
    except YearlyHerdReport.DoesNotExist:
        return None


def get_yearly_reports(round_id: int, genebank_id: int) -> list[dict]:
    """Get all yearly reports for a specific round and genebank."""
    try:
        with DATABASE.atomic():
            reports = (
                YearlyHerdReport.select(YearlyHerdReport, Herd)
                .join(Herd)
                .where((YearlyHerdReport.round == round_id) & (Herd.genebank == genebank_id))
            )

            formatted_reports = []
            for r in reports:
                # Parse the JSON data field
                form_data = json.loads(r.data) if r.data else {}

                # Determine status based on the report data
                status = "Aktiv genbank"  # Default status
                if form_data.get("endingGenbank", False):
                    status = "Vill avsluta genbank"
                else:
                    males = form_data.get("numberOfMalesWithCertificate", 0)
                    females = form_data.get("numberOfFemalesWithCertificate", 0)
                    if males == 0 and females == 0:
                        status = "Automatisk avslutad: Saknar djur med intyg"
                    elif males == 0:
                        status = "Automatisk avslutad: Saknar hane med intyg"
                    elif females == 0:
                        status = "Automatisk avslutad: Saknar hona med intyg"

                # Format publish information based on allowPublication array
                publish_info = "Nej, ingen publicering"
                allow_publication = form_data.get("allowPublication", [])

                if "noPublication" in allow_publication:
                    publish_info = "Nej, ingen publicering"
                elif "all" in allow_publication:
                    excluded = []
                    if "noPhone" in allow_publication:
                        excluded.append("telefonnummer")
                    if "noEmail" in allow_publication:
                        excluded.append("e-postadress")
                    if "noAddress" in allow_publication:
                        excluded.append("postnummer och ort")

                    if not excluded:
                        publish_info = "Ja för publicering i Koharen"
                    else:
                        publish_info = f"Ja, men inte {' och '.join(excluded)}"
                else:
                    # Handle individual publication settings
                    excluded = []
                    if "noPhone" in allow_publication:
                        excluded.append("telefonnummer")
                    if "noEmail" in allow_publication:
                        excluded.append("e-postadress")
                    if "noAddress" in allow_publication:
                        excluded.append("postnummer och ort")

                    if excluded:
                        publish_info = f"Ja, men inte {' och '.join(excluded)}"
                    else:
                        publish_info = "Ja för publicering i Koharen"

                report = {
                    "herd": r.herd.herd,  # Changed from genebank_number to herd
                    "name": r.herd.herd_name,
                    "status": status,
                    # Form data fields
                    "litter_count": form_data.get("numberOfLitters", 0),
                    "total_kits_born": form_data.get("totalBorn", 0),
                    "living_kits_6weeks": form_data.get("totalAliveAfterSixWeeks", 0),
                    "registered_females_yearend": form_data.get("numberOfFemalesWithCertificate", 0),
                    "registered_males_yearend": form_data.get("numberOfMalesWithCertificate", 0),
                    "breeding_females_used": form_data.get("numberOfFemalesUsedInBreeding", 0),
                    "breeding_males_used": form_data.get("numberOfMalesUsedInBreeding", 0),
                    # Privacy settings
                    "publish": publish_info,
                    # Contact and bank info - access through the joined Herd model
                    "email": (r.herd.email if "noEmail" not in allow_publication else None),
                    "phone": (r.herd.mobile_phone if "noPhone" not in allow_publication else None),
                    "address": (r.herd.physical_address if "noAddress" not in allow_publication else None),
                    "bank_account": r.herd.bank_account_number,
                    "bank_name": r.herd.bank_name,
                    # Additional fields
                    "eligible_for_support": form_data.get("eligibleForSupport", False),
                    "defects_malformations": form_data.get("defectsMalformations", ""),
                    # Disease cases from form data
                    "disease_cases": format_disease_cases(form_data.get("diseases", {})),
                    "submission_date": (r.report_date.strftime("%Y-%m-%d") if r.report_date else None),
                    "fullname": r.generated_by.fullname,
                }
                formatted_reports.append(report)

            return formatted_reports
    except Exception as e:
        logger.error(f"Failed to get yearly reports: {str(e)}")
        raise


def format_disease_cases(diseases: dict) -> str:
    """Format disease cases into a readable string."""
    cases = []
    for disease, data in diseases.items():
        if data.get("numberOfAffectedRabbits"):
            if disease == "other" and data.get("diseaseName"):
                cases.append(f"{data['diseaseName']}: {data['numberOfAffectedRabbits']} ({data.get('age', '')})")
            else:
                cases.append(f"{disease}: {data['numberOfAffectedRabbits']} ({data.get('age', '')})")
    return "; ".join(cases) if cases else "Inga rapporterade sjukdomsfall"


def export_yearly_reports_csv(round_id: int, genebank_id: int) -> str:
    """Export yearly reports as CSV data."""
    try:
        reports = get_yearly_reports(round_id, genebank_id)

        # CSV Headers in Swedish - exactly matching the table view
        headers = [
            "Besättningsnummer",
            "Namn",
            "Status",
            "Antal kullar under året",
            "Totalt antal födda ungar under året",
            "Totalt antal levande ungar efter 6 veckor",
            "Registrerade honor vid årsskiftet i genbanken, antal",
            "Registrerade hanar vid årsskiftet i genbanken, antal",
            "Använda honor i avel under året, antal",
            "Använda hanar i avel under året, antal",
            "Publicering i Koharen",
            "E-post",
            "Uppfyller kraven för stöd",
            "Bankkontonr",
            "Bank",
            "Defekter/missbildningar",
            "Sjukdomsfall under året",
            "Datum för ifyllnad",
            "Ifylld av",
        ]

        buf = io.StringIO()
        # QUOTE_ALL: a CR, LF or separator inside a value can never start a new cell or row.
        writer = csv.writer(buf, delimiter=";", lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(headers)
        for report in reports:
            writer.writerow(
                [
                    csv_cell(v)
                    for v in (
                        report["herd"],
                        report["name"],
                        report["status"],
                        report["litter_count"],
                        report["total_kits_born"],
                        report["living_kits_6weeks"],
                        report["registered_females_yearend"],
                        report["registered_males_yearend"],
                        report["breeding_females_used"],
                        report["breeding_males_used"],
                        report["publish"],
                        report["email"],
                        "Ja" if report["eligible_for_support"] else "Nej",
                        report["bank_account"],
                        report["bank_name"],
                        report["defects_malformations"],
                        report["disease_cases"] or "Inga rapporterade sjukdomsfall",
                        report["submission_date"],
                        report["fullname"],
                    )
                ]
            )

        # Add BOM for Excel to properly detect UTF-8
        return "\ufeff" + buf.getvalue().rstrip("\n")
    except Exception as e:
        logger.error(f"Failed to export yearly reports as CSV: {str(e)}")
        raise


# ---------------------------------------------------------------------------
# Audit log helpers
# ---------------------------------------------------------------------------

# Maps audited table → lambda to resolve genebank_id from record_id.
# hbuser is intentionally excluded — audit access for hbuser is admin-only.
_AUDIT_GENEBANK_LOOKUP = {
    "individual": lambda rid: Individual.get_by_id(int(rid)).origin_herd.genebank_id,
    "breeding": lambda rid: Breeding.get_by_id(int(rid)).breeding_herd_id.genebank_id,
    "bunny": lambda rid: Bunny.get_by_id(int(rid)).breeding.breeding_herd_id.genebank_id,
    "herd": lambda rid: Herd.get_by_id(int(rid)).genebank_id,
    "weight": lambda rid: Weight.get_by_id(int(rid)).individual.origin_herd.genebank_id,
    "bodyfat": lambda rid: Bodyfat.get_by_id(int(rid)).individual.origin_herd.genebank_id,
    "individualdisease": lambda rid: IndividualDisease.get_by_id(int(rid)).individual.origin_herd.genebank_id,
    "herd_tracking": lambda rid: HerdTracking.get_by_id(int(rid)).herd.genebank_id,
    "color": lambda rid: Color.get_by_id(int(rid)).genebank_id,
}


def get_audit_genebank_id(table_name, record_id):
    """Resolve genebank_id from a table name and record ID.
    Returns genebank_id or None if table is hbuser or record not found."""
    lookup = _AUDIT_GENEBANK_LOOKUP.get(table_name)
    if lookup is None:
        return None
    try:
        return lookup(record_id)
    except (DoesNotExist, AttributeError):
        return None


# Broad safety net. Primary target is auth_data
# (current schema); password_hash / password / salt cover any pre-v6
# rows and future accidental leaks from renamed columns.
SENSITIVE_AUDIT_KEYS = frozenset(
    {
        "auth_data",  # authenticators.auth_data — current password path
        "password_hash",  # hbuser.password_hash — belt for pre-v6 audit rows
        "password",  # generic — any table
        "salt",  # generic — any table
    }
)
# Extend when adding a new sensitive column anywhere in AUDITED_TABLES.


def _strip_sensitive(row):
    for key in ("old_data", "new_data"):
        payload = row.get(key)
        if isinstance(payload, dict):
            for k in SENSITIVE_AUDIT_KEYS:
                payload.pop(k, None)
    return row


def query_audit_log(
    *,
    table_name=None,
    record_id=None,
    changed_by=None,
    date_from=None,
    date_to=None,
    operation=None,
    page=1,
    per_page=50,
):
    """
    Paginated audit_log reader for the v2 adminpanel.

    Default sort changed_at DESC (index-served); per_page hard-capped at
    200. Every returned row passes _strip_sensitive() regardless of age. Runs under a 5 s statement_timeout — a tripped
    timeout surfaces as peewee.OperationalError, which the route maps to a 503
    problem+json.
    """
    q = AuditLog.select()
    if table_name:
        q = q.where(AuditLog.table_name == table_name)
    if record_id:
        q = q.where(AuditLog.record_id == record_id)
    if changed_by:
        q = q.where(AuditLog.changed_by == changed_by)
    if date_from:
        q = q.where(AuditLog.changed_at >= date_from)
    if date_to:
        q = q.where(AuditLog.changed_at <= date_to)
    if operation:
        q = q.where(AuditLog.operation == operation)

    page = max(page, 1)
    per_page = min(max(per_page, 1), 200)  # hard cap

    with DATABASE.atomic():
        # Flask-side query timeout — scoped to this transaction.
        DATABASE.execute_sql("SET LOCAL statement_timeout = '5s'")
        total = q.count()
        rows = [
            _strip_sensitive(
                {
                    "id": r.id,
                    "table_name": r.table_name,
                    "record_id": r.record_id,
                    "operation": r.operation,
                    "old_data": r.old_data,
                    "new_data": r.new_data,
                    "changed_fields": r.changed_fields,
                    "changed_by": r.changed_by,
                    "changed_at": r.changed_at.isoformat() if r.changed_at else None,
                }
            )
            for r in q.order_by(AuditLog.changed_at.desc()).paginate(page, per_page)
        ]
    return {"rows": rows, "total": total, "page": page, "per_page": per_page}


def get_online_users(minutes=5):
    """
    Users active within the last `minutes`. Thin read for the
    admin-only endpoint — auth lives in @admin_required, unlike the
    legacy get_active_users() which serves /api/active_users and stays
    untouched.
    """
    threshold = datetime.now() - timedelta(minutes=minutes)
    q = User.select().where(User.last_active >= threshold).order_by(User.last_active.desc())
    return [
        {
            "username": u.username,
            "fullname": u.fullname,
            "last_active": u.last_active.isoformat() if u.last_active else None,
        }
        for u in q
    ]


def get_demo_sync_status():
    """
    Latest demo_sync_status row + staleness flag.

    Raw SQL by design: the table is operational telemetry written by
    scripts/sync-demo-db.sh, not member data (not in AUDITED_TABLES).
    `stale` = the newest FINISHED run is older than 26 h — the cron is
    nightly, so >26 h means it did not run; a still-running latest row
    does not reset staleness. Empty table → stale with all-null fields.
    """
    cursor = DATABASE.execute_sql(
        """
        SELECT started_at, finished_at, success, detail, rows_synced,
               (SELECT coalesce(max(finished_at) >= now() - interval '26 hours', false)
                FROM demo_sync_status WHERE finished_at IS NOT NULL) AS fresh
        FROM demo_sync_status
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        return {
            "started_at": None,
            "finished_at": None,
            "success": None,
            "detail": None,
            "rows_synced": None,
            "stale": True,
        }
    started_at, finished_at, success, detail, rows_synced, fresh = row
    return {
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "success": success,
        "detail": detail,
        "rows_synced": rows_synced,
        "stale": not fresh,
    }


def _genebank_letters():
    """Genebank id -> initial letter (Gotland→G, Mellerud→M) for role_summary."""
    return {gb.id: gb.name[:1].upper() for gb in Genebank.select()}


def _role_summary(user, letters):
    """
    Short computed role label:
    "admin" | "manager(G,M)" | "helper(G)" | "viewer(G)" | "owner(2 besättningar)" |
    "ingen roll". Precedence: admin > manager > viewer > owner.
    matrikel_admin is no studbook role and is never hidden by that
    precedence: it is appended ("manager(G) + matrikel_admin") or stands
    alone, so the panel shows who may write the member registry.
    """
    privs = user.privileges
    label = _studbook_role_summary(privs, letters)
    if any(p.get("level") == "matrikel_admin" for p in privs):
        return "matrikel_admin" if label == "ingen roll" else f"{label} + matrikel_admin"
    return label


def _studbook_role_summary(privs, letters):
    if any(p.get("level") == "admin" for p in privs):
        return "admin"
    for level in ("manager", "helper", "viewer"):
        ids = [p.get("genebank") for p in privs if p.get("level") == level]
        if ids:
            return f"{level}({','.join(letters.get(i, '?') for i in ids)})"
    owners = [p for p in privs if p.get("level") == "owner"]
    if owners:
        n = len(owners)
        return f"owner({n} besättning{'ar' if n != 1 else ''})"
    return "ingen roll"


def _admin_user_row(u, letters):
    """List-row shape (S3.8 AdminUserListItem) — detail extends this."""
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "fullname": u.fullname,
        "validated": bool(u.validated),
        "v2_prod_access": bool(u.v2_prod_access),
        "is_active": bool(u.is_active),
        "last_active": u.last_active.isoformat() if u.last_active else None,
        "role_summary": _role_summary(u, letters),
        "google_linked": bool(u.google_email),
    }


def list_admin_users(
    *,
    role=None,
    validated=None,
    active=None,
    v2_prod_access=None,
    active_since=None,
    search=None,
    page=1,
    per_page=25,
    sort="last_active",
    direction="desc",
):
    """
    Paginated admin user list. validated/active/v2_prod_access/
    active_since/search sort in SQL; the role filter runs Python-side
    (privileges live in a TEXT JSON column) BEFORE total/slicing so
    pagination stays correct — hbuser is small (hundreds of rows).
    """
    q = User.select()
    if validated is not None:
        q = q.where(User.validated == validated)
    if active is not None:
        q = q.where(User.is_active == active)
    if v2_prod_access is not None:
        q = q.where(User.v2_prod_access == v2_prod_access)
    if active_since is not None:
        q = q.where(User.last_active >= active_since)
    if search:
        s = f"%{search}%"
        q = q.where((User.username**s) | (User.email**s) | (User.fullname**s))
    sort_map = {
        "username": User.username,
        "email": User.email,
        "fullname": User.fullname,
        "last_active": User.last_active,
    }
    field = sort_map.get(sort, User.last_active)
    q = q.order_by(field.desc() if direction == "desc" else field.asc())

    users = list(q)
    if role == "none":
        users = [u for u in users if not u.privileges]
    elif role:
        users = [u for u in users if any(p.get("level") == role for p in u.privileges)]

    total = len(users)
    page = max(page, 1)
    per_page = min(max(per_page, 1), 200)
    start = (page - 1) * per_page
    letters = _genebank_letters()
    return {
        "users": [_admin_user_row(u, letters) for u in users[start : start + per_page]],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def get_admin_user_detail(u_id):
    """
    Full admin user detail: the list row + uuid, _privileges,
    picture/google fields (S3.8 AdminUserDetail). Returns None if the
    user does not exist. NOTE: hbuser has no created_at column today
    (database.py:929) — omitted per the spec's verify-at-impl clause.
    """
    u = User.get_or_none(User.id == u_id)
    if u is None:
        return None
    row = _admin_user_row(u, _genebank_letters())
    row.update(
        {
            "uuid": str(u.uuid),
            "_privileges": u.privileges,
            "profile_picture": u.profile_picture,
            "google_picture": u.google_picture,
            "google_name": u.google_name,
            "google_email": u.google_email,
            "use_google_picture": bool(u.use_google_picture),
        }
    )
    return row


def edit_admin_user(u_id, fields):
    """
    Admin-only profile update. `fields` is a pre-validated
    subset of {fullname, email} — role writes go through update_role
    (POST /api/v2/admin/role) and flags through their dedicated endpoints;
    the endpoint rejects everything else before calling this.
    """
    user = User.get_or_none(User.id == u_id)
    if user is None:
        raise ValueError("user-not-found")
    if "fullname" in fields:
        user.fullname = fields["fullname"]
    if "email" in fields:
        user.email = fields["email"]
    # Only the edited columns, never a stale is_active/_privileges.
    only = [getattr(User, f) for f in ("fullname", "email") if f in fields]
    if only:
        user.save(only=only)
    return get_admin_user_detail(u_id)


def set_v2_prod_access(u_id, enabled):
    """Toggle hbuser.v2_prod_access. Audited via trigger."""
    user = User.get_or_none(User.id == u_id)
    if user is None:
        raise ValueError("user-not-found")
    user.v2_prod_access = bool(enabled)
    user.save(only=[User.v2_prod_access])  # never a stale is_active/_privileges
    return {"id": user.id, "v2_prod_access": bool(user.v2_prod_access)}


def set_validated(u_id, validated):
    """
    Toggle hbuser.validated: the course is done. Google login (redirect and
    token flows) requires it; session load and password login do not check
    it. Audited via trigger.
    """
    user = User.get_or_none(User.id == u_id)
    if user is None:
        raise ValueError("user-not-found")
    user.validated = bool(validated)
    user.save(only=[User.validated])  # never a stale is_active/_privileges
    return {"id": user.id, "validated": bool(user.validated)}


def get_audit_history(table_name, record_id, page=1, per_page=25, changed_by=None, from_date=None, to_date=None):
    """Returns paginated audit log entries for a specific record."""
    per_page = min(per_page, 100)

    query = AuditLog.select().where(AuditLog.table_name == table_name).where(AuditLog.record_id == str(record_id))

    if changed_by:
        query = query.where(AuditLog.changed_by == changed_by)
    if from_date:
        query = query.where(AuditLog.changed_at >= from_date)
    if to_date:
        query = query.where(AuditLog.changed_at <= to_date)

    total = query.count()
    entries = query.order_by(AuditLog.changed_at.desc()).paginate(page, per_page)

    return {
        "status": "success",
        "data": [
            {
                "id": e.id,
                "schema_name": e.schema_name,
                "operation": e.operation,
                "changed_fields": e.changed_fields,
                "old_data": e.old_data,
                "new_data": e.new_data,
                "changed_by": e.changed_by,
                "changed_at": e.changed_at.isoformat() if e.changed_at else None,
                "transaction_id": e.transaction_id,
            }
            for e in entries
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


# Columns the generic audit undo never writes. The domain services keep state derived from
# them in step and guard the change; a raw UPDATE here would bypass both.
# - bunny.individual_id: the roster link, owned by promote/unpromote (certificate guard, voiding).
#   bunny.fate is not listed: the bunny CHECK refuses a fate that disagrees with the link, so
#   undoing the fate of an unlinked bunny works and a lifecycle undo cannot half-apply. A restore
#   whose snapshot holds another link skips fate along with it.
# - individual: origin_herd_id and breeding_id (the BIRTH herd_tracking row, the litter's pedigree
#   check), number (certificate PDF and photo keys), digital_certificate and certificate (digital
#   is issued only with a signed PDF and clears the paper one; clearing either opens unpromote's
#   certificate guard), voided, voided_at, is_active.
# - breeding: birth_date and breeding_herd_id (the kits' BIRTH rows and numbers), litter_number
#   (the kits' numbers; renumbering passes through a temporary negative value).
_AUDIT_UNDO_SKIP = {
    "bunny": {"individual_id"},
    "individual": {
        "origin_herd_id",
        "breeding_id",
        "number",
        "digital_certificate",
        "certificate",
        "voided",
        "voided_at",
        "is_active",
    },
    "breeding": {"birth_date", "breeding_herd_id", "litter_number"},
}


# A herd's identity and ownership are admin-only, as in update_herd (the primary key herd_id is
# never written by undo). Its *_privacy columns hold None or one of the levels update_herd accepts.
_AUDIT_HERD_ADMIN_COLUMNS = {"herd", "genebank_id", "membership_id"}
_AUDIT_PRIVACY_LEVELS = ("public", "authenticated", "private")


# shortcut: same contract as invalid_privacy_field in the herd-privacy fix; call that once it is merged.
def _audit_invalid_privacy_field(fields):
    """The first *_privacy column in `fields` that holds anything but None or a privacy level, else None."""
    bad = (k for k, v in fields.items() if k.endswith("_privacy") and v not in (None, *_AUDIT_PRIVACY_LEVELS))
    return next(bad, None)


def _audit_undo_locked(table_name, is_admin):
    """The columns of `table_name` that an audit revert/restore by this user must not write."""
    locked = _AUDIT_UNDO_SKIP.get(table_name, set())
    if table_name == "herd" and not is_admin:
        return locked | _AUDIT_HERD_ADMIN_COLUMNS
    return locked


def _audit_undo_refusal(table_name, values, is_admin):
    """
    Why an audit revert/restore that writes `values` (column -> value) to `table_name` is refused,
    or None. A restore leaves the locked columns out of `values` first: it skips them.
    """
    held = ", ".join(sorted(set(values) & _audit_undo_locked(table_name, is_admin)))
    if held and table_name == "herd":
        return f"Bara admin kan ändra {held} på en besättning."
    if held:
        return f"{held} kan inte ångras eller återställas här. Ändra via kaninen, kullen eller kullplatsen i stället."
    if table_name == "herd" and (bad := _audit_invalid_privacy_field(values)):
        return f"Ogiltigt värde för {bad}: måste vara public, authenticated, private eller null."
    return None


def _stored_row(table_name, pk_col, record_id):
    """The stored row of `table_name`/`record_id` as the JSON the audit snapshots use, or None."""
    row = DATABASE.execute_sql(
        f'SELECT row_to_json(t) FROM "{table_name}" t WHERE "{pk_col}" = %s', (record_id,)
    ).fetchone()
    return row[0] if row else None


def _audit_pedigree_cycle_error(table_name, record_id, values):
    """
    Why an audit revert/restore that writes `values` (column -> value) to `table_name`/`record_id`
    is refused (a pedigree cycle or a voided parent), or None. Takes the herd-tracking locks in the global
    order first, so a concurrent update_breeding/update_individual/unpromote on the same rows
    serialises with the check. Also refuses litter sizes that would leave more alive at 6 weeks than born,
    the rule update_breeding enforces, decided on the row locked here and, as there, only when a size
    changes: a restore that writes back a historical row's unchanged sizes is not refused for them.
    """
    if table_name == "breeding" and ("litter_size" in values or "litter_size6w" in values):
        stored = Breeding.select().where(Breeding.id == int(record_id)).for_update().get_or_none()
        if stored is not None:
            stored_sizes = (stored.litter_size, stored.litter_size6w)
            sizes = (values.get("litter_size", stored_sizes[0]), values.get("litter_size6w", stored_sizes[1]))
            if sizes != stored_sizes and None not in sizes and int(sizes[1]) > int(sizes[0]):
                return LITTER_SIZE6W_ABOVE_BORN
    if table_name == "breeding" and ("father_id" in values or "mother_id" in values):
        stored = Breeding.select().where(Breeding.id == int(record_id)).for_update().get_or_none()
        if stored is None:
            return None
        father = values.get("father_id", stored.father_id)
        mother = values.get("mother_id", stored.mother_id)
        if (father, mother) == (stored.father_id, stored.mother_id):
            return None
        kits = Individual.select(Individual.id).where(Individual.breeding_id == stored.id)
        kit_ids = [kit.id for kit in kits]
        new_parents = [p for p in (father, mother) if p is not None and p not in (stored.father_id, stored.mother_id)]
        lock_individuals(kit_ids + new_parents)
        # An unpromoted (voided) rabbit cannot become a parent again; decided under its lock.
        if Individual.select().where(Individual.id.in_(new_parents) & Individual.voided).exists():
            return "Föräldern är makulerad och kan inte återställas"
        return pedigree_cycle_error(kit_ids, father, mother)
    return None


# Rows not written by the trigger (schema_name 'v1': the old Stamboken's change
# logs, imported once at cutover by a script in the ops repo) hold partial
# snapshots in v1's value format.
IMPORTED_AUDIT_MESSAGE = "Historik från gamla Stamboken kan inte ångras"


def revert_audit_entry(audit_id, fields=None, is_admin=False):
    """Revert specific fields (or all) from an UPDATE audit entry.
    Returns (dict, status_code) tuple."""
    try:
        entry = AuditLog.get_by_id(audit_id)
    except AuditLog.DoesNotExist:
        return {"status": "error", "message": "Granskningsposten finns inte"}, 404

    if entry.schema_name != "public":
        return {"status": "error", "message": IMPORTED_AUDIT_MESSAGE}, 400

    if entry.operation != "UPDATE":
        return {"status": "error", "message": "Kan bara ångra UPDATE-poster"}, 400

    if entry.old_data is None:
        return {"status": "error", "message": "Ingen gammal data att ångra till"}, 400

    table_name = entry.table_name
    if table_name not in AUDITED_TABLES:
        return {"status": "error", "message": "Okänd tabell"}, 400

    pk_col = AUDITED_TABLES[table_name][0]

    if fields is None:
        fields = entry.changed_fields or []
    else:
        # Only allow fields that were actually changed in this entry
        allowed = set(entry.changed_fields or [])
        invalid = [f for f in fields if f not in allowed]
        if invalid:
            return {"status": "error", "message": f"Fälten ändrades inte i denna post: {invalid}"}, 400

    valid_cols = {c.name for c in DATABASE.get_columns(table_name)}

    set_clauses = []
    params = []
    values = {}
    for field in fields:
        if field == pk_col:
            continue
        if field not in valid_cols:
            return {"status": "error", "message": f"Ogiltigt fält: {field}"}, 400
        if field in entry.old_data:
            set_clauses.append(f'"{field}" = %s')
            params.append(entry.old_data[field])
            values[field] = entry.old_data[field]

    if refusal := _audit_undo_refusal(table_name, values, is_admin):
        return {"status": "error", "message": refusal}, 409

    if not set_clauses:
        return {"status": "error", "message": "Inga fält att ångra"}, 400

    params.append(entry.record_id)

    try:
        with DATABASE.atomic():
            if cycle := _audit_pedigree_cycle_error(table_name, entry.record_id, values):
                return {"status": "error", "message": cycle}, 409
            cursor = DATABASE.execute_sql(
                f'UPDATE "{table_name}" SET {", ".join(set_clauses)} WHERE "{pk_col}" = %s',
                params,
            )
            if cursor.rowcount == 0:
                return {"status": "error", "message": "Posten hittades inte"}, 404
    except Exception as e:
        return {"status": "error", "message": f"Ångra misslyckades: {e}"}, 409

    return {"status": "success", "message": "Ändring ångrad"}, 200


def restore_record(table_name, record_id, audit_id, is_admin=False):
    """Restore a record to the state before a specific audit entry.
    Returns (dict, status_code) tuple."""
    if table_name not in AUDITED_TABLES:
        return {"status": "error", "message": "Okänd tabell"}, 400

    try:
        entry = AuditLog.get_by_id(audit_id)
    except AuditLog.DoesNotExist:
        return {"status": "error", "message": "Granskningsposten finns inte"}, 404

    if entry.table_name != table_name or entry.record_id != str(record_id):
        return {"status": "error", "message": "Granskningsposten matchar inte posten"}, 400

    if entry.schema_name != "public":
        return {"status": "error", "message": IMPORTED_AUDIT_MESSAGE}, 400

    if entry.operation != "UPDATE":
        return {"status": "error", "message": "Kan bara återställa från UPDATE-poster"}, 400

    snapshot = entry.old_data
    if snapshot is None:
        return {"status": "error", "message": "Ingen ögonblicksbild tillgänglig"}, 400

    # Restore-time excluded set = snapshot_excluded: those fields are absent
    # from snapshots and cannot be restored.
    pk_col, snapshot_excluded, _cde = AUDITED_TABLES[table_name]
    valid_cols = {c.name for c in DATABASE.get_columns(table_name)}
    # Skip PK, snapshot-excluded columns, and unknown columns
    skip = {pk_col} | set(snapshot_excluded)

    wanted = {field: value for field, value in snapshot.items() if field not in skip and field in valid_cols}
    current = _stored_row(table_name, pk_col, record_id)
    if current is None:
        return {"status": "error", "message": "Posten hittades inte"}, 404
    # Locked columns are skipped and the rest of the snapshot is restored. They are never written,
    # not even with the value they already hold: a domain service may change them before the UPDATE.
    locked = _audit_undo_locked(table_name, is_admin)
    if table_name == "bunny" and current.get("individual_id") != wanted.get("individual_id"):
        locked = locked | {"fate"}  # the bunny CHECK ties fate to the link, which restore skips
    values = {field: value for field, value in wanted.items() if field not in locked}
    if refusal := _audit_undo_refusal(table_name, values, is_admin):
        return {"status": "error", "message": refusal}, 409
    skipped = sorted(field for field in locked & wanted.keys() if current.get(field) != wanted[field])
    set_clauses = [f'"{field}" = %s' for field in values]
    params = list(values.values())

    if not set_clauses:
        return {"status": "error", "message": "Inget att återställa"}, 400

    params.append(record_id)

    try:
        with DATABASE.atomic():
            if cycle := _audit_pedigree_cycle_error(table_name, record_id, values):
                return {"status": "error", "message": cycle}, 409
            cursor = DATABASE.execute_sql(
                f'UPDATE "{table_name}" SET {", ".join(set_clauses)} WHERE "{pk_col}" = %s',
                params,
            )
            if cursor.rowcount == 0:
                return {"status": "error", "message": "Posten hittades inte"}, 404
    except Exception as e:
        return {"status": "error", "message": f"Återställning misslyckades: {e}"}, 409

    if skipped:
        why = "bara admin kan ändra dem" if table_name == "herd" else "de ändras via kaninen, kullen eller kullplatsen"
        return {"status": "success", "message": f"Post återställd utom {', '.join(skipped)}: {why}."}, 200
    return {"status": "success", "message": "Post återställd"}, 200


# GDPR — jsonb keys stripped from audit_log snapshots when a user
# exercises the right to erasure. Every hbuser field whose snapshot
# identifies the person.
# Extend when adding new PII columns to hbuser.
PII_KEYS = [
    "email",
    "fullname",
    "google_email",
    "google_name",
    "profile_picture",
    "google_picture",
    "username",
    "uuid",
]


def purge_user_audit_pii(user_id: int, username: str, email: str) -> int:
    """GDPR Article 17 right-to-erasure helper for audit_log.

    Redacts PII_KEYS from old_data/new_data on every audit_log row about
    the user (table_name='hbuser' AND record_id=<user_id>) or WRITTEN BY
    them (changed_by IN (username, email) — changed_by stores
    current_user.username-or-email, never the numeric id. Pseudonymises
    changed_by to 'raderad-<user_id>' and NULLs ip_address on matched
    rows. One transaction with the same DROP RULE → UPDATE → marker →
    CREATE RULE sequence as the credential-redaction migration; Postgres DDL is
    transactional, so a rollback also restores the rule.
    In the same transaction the free text of the user's command log rows
    goes too (ADR-0017); the actor id stays as their pseudonym.

    The caller must capture username and email BEFORE deleting the hbuser
    row. Returns the number of rows redacted (0 for a fresh account).
    NOT wired to any endpoint in Phase 17 — user deletion is out of scope;
    a future deletion endpoint calls this inside the same request atomic().
    """
    pseudonym = f"raderad-{user_id}"
    marker_id = "purge-user-{}-{}".format(user_id, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    with DATABASE.atomic():
        # Before the DROP RULE: it locks audit_log exclusively until commit, and an Undo that holds one of these
        # rows writes audit_log through its trigger, so the other order can deadlock.
        purge_command_free_text(datetime.now(timezone.utc), actor_id=user_id)  # the actor stays: a pseudonym
        DATABASE.execute_sql("DROP RULE IF EXISTS audit_log_no_update ON audit_log")
        cursor = DATABASE.execute_sql(
            """
            UPDATE audit_log
            SET old_data   = old_data - %s::text[],
                new_data   = new_data - %s::text[],
                changed_by = CASE WHEN changed_by IN (%s, %s)
                                  THEN %s ELSE changed_by END,
                ip_address = NULL
            WHERE (table_name = 'hbuser' AND record_id = %s)
               OR changed_by IN (%s, %s)
            """,
            (
                PII_KEYS,
                PII_KEYS,
                username,
                email,
                pseudonym,
                str(user_id),
                username,
                email,
            ),
        )
        rows_redacted = cursor.rowcount or 0
        if rows_redacted == 0:
            logger.warning(
                "purge_user_audit_pii: no audit rows matched user %s "
                "(fine for a fresh account, suspicious for an old one)",
                user_id,
            )
        # Marker row — documents the erasure, not the erased content; only
        # the numeric user_id survives, which IS the pseudonym key.
        DATABASE.execute_sql(
            """
            INSERT INTO audit_log
                (table_name, record_id, operation, new_data, changed_by)
            VALUES
                ('audit_log', %s, 'REDACT',
                 jsonb_build_object('rows_redacted', %s::int), 'system')
            """,
            (marker_id, rows_redacted),
        )
        DATABASE.execute_sql("CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING")
    return rows_redacted


# Session-store counter of mass logouts. Outside 'session:*', so the sweep never
# deletes it, and without a TTL: it must outlive every session issued before it.
LOGOUT_EPOCH_KEY = "logout-epoch"


def mass_logout_sessions(redis_client, changed_by):
    """
    Emergency mass logout: SCAN+DEL every
    'session:*' key in the Flask-Session Redis store (db 2). SCAN+DEL,
    not FLUSHDB — an unrelated key in the db is never collateral.

    No DB table changes → the Phase 4 trigger cannot record this, so an
    explicit audit_log marker row is written (same pattern as the audit PII
    purge marker). Returns the number of deleted session keys.

    Deleting the keys is not enough on its own: a request in flight during
    the sweep writes its session back when it ends. So the logout
    epoch is incremented first, and every session stamped with an older one
    is refused (herdbook._session_revoked); the sweep only cleans up. INCR,
    not a timestamp: it is atomic and needs no clock, so overlapping mass
    logouts can never move the epoch backwards.
    """
    redis_client.incr(LOGOUT_EPOCH_KEY)
    cleared = 0
    batch = []
    for key in redis_client.scan_iter(match="session:*", count=500):
        batch.append(key)
        if len(batch) >= 500:
            cleared += redis_client.delete(*batch)
            batch = []
    if batch:
        cleared += redis_client.delete(*batch)

    AuditLog.create(
        table_name="hbuser",
        record_id=f"mass-logout-{datetime.now(timezone.utc).isoformat()}",
        operation="SYSTEM",
        new_data={"sessions_cleared": cleared},
        changed_by=changed_by,
    )
    return cleared
