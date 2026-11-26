#!/usr/bin/env python3
"""
Database handler for 'the herdbook'.
"""
# pylint: disable=too-many-lines

import json
import logging
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from peewee import (
    JOIN,
    SQL,
    AutoField,
    BigAutoField,
    BigIntegerField,
    BooleanField,
    CharField,
    Check,
    DateField,
    DateTimeField,
    DeferredForeignKey,
    DoesNotExist,
    FloatField,
    ForeignKeyField,
    IntegerField,
    Model,
    OperationalError,
    PostgresqlDatabase,
    Proxy,
    Select,
    SmallIntegerField,
    SqliteDatabase,
    TextField,
    UUIDField,
    fn,
)
from playhouse.migrate import PostgresqlMigrator, SqliteMigrator, migrate
from playhouse.postgres_ext import ArrayField, BinaryJSONField
from playhouse.shortcuts import ReconnectMixin

import utils.settings as settings
from utils.certificate_lifecycle import state_of
from utils.postal import format_postal_address, split_postal_address


class ReconnectPostgresqlDatabase(ReconnectMixin, PostgresqlDatabase):
    """PostgresqlDatabase with automatic reconnect on connection loss."""

    pass


# 23 from develop (DigitalCertificateV2, litter_number, bunny roster) + the two
# Phase-8 member-registry migrations renumbered onto the tail (24, 25) + the
# Member Model v2 expand (26) and contract (27) migrations + Phase 17 admin
# (28: split-exclusion audit triggers, is_active, demo_sync_status) + Phase 19
# medlem/profil (29: structured postal address, member.user_id unique link) +
# Phase 999.5 herd tracking kind/void (30) + Phase 999.8 genetics version (31) + genetics history (32) +
# history algorithm version (33) + genetics epoch (34) + the individual command log (35) +
# Individual.microchip (36) + billing address on membership and member_application (37) +
# retiring the PDF rows of digital certificates that a paper certificate replaced (38) +
# audit_log IP retention index (39) + herd bank privacy reset (40) + the mail queue (41) +
# the intake queue (42) and its retention (43) + buyer_contact (44) +
# matrikel_audit rows without a user, written by the nightly anonymization (45) +
# the coat column individual.rex (46) + hbuser.name_on_check_page and digitalcertificatev2.issued_as (47) +
# one account per Google identity (48) + one-time codes and members' previous addresses (49) +
# the herd's contact from the member register, herd.contact_member and herd.contact_pending (50) +
# the yearly report v2 (51) + organization name and number on membership (52) +
# notice.individual and buyer_contact.erased_email_hash (53) +
# acceptance of the account rules (54) + each history year's realised Ne (55) +
# a paper certificate's copy checked against the registry, inbox_document.saved_certificate and saved_number,
# verified_at and verified_by (56) + a buyer's e-mail kept only for the notice, buyer_contact.email_notice_only (57) +
# the support account on the membership, with its type (58).
CURRENT_SCHEMA_VERSION = 58
# classid half of the two-int advisory lock that serializes migration replays
# across processes (each gunicorn worker imports the app and calls
# check_migrations). The objid half is hashtext(current_database()) — advisory
# locks are server-wide and herdbook/herdbook_demo share a postgres instance.
MIGRATION_LOCK_KEY = 0x48424D47  # "HBMG"
DB_PROXY = Proxy()
DATABASE = None
DATABASE_MIGRATOR = None

logger = logging.getLogger("herdbook.db")


def set_test_database(name):
    """
    This function sets the database to a named sqlite3 database for testing.
    """
    global DATABASE, DATABASE_MIGRATOR  # pylint: disable=global-statement
    DATABASE = SqliteDatabase(name)

    # Assume Sqlite to be connected always.
    DB_PROXY.initialize(DATABASE)

    DATABASE_MIGRATOR = SqliteMigrator(DATABASE)


def set_database(name, host=None, port=None, user=None, password=None):
    """
    This function makes it possible to set the database manually when settings
    aren't loaded.
    """
    global DATABASE, DATABASE_MIGRATOR  # pylint: disable=global-statement
    DATABASE = ReconnectPostgresqlDatabase(name, host=host, port=port, user=user, password=password)

    DB_PROXY.initialize(DATABASE)

    DATABASE_MIGRATOR = PostgresqlMigrator(DATABASE)


# Check if PostgreSQL env vars are set (for CI testing with real database)
_pg_host = os.getenv("POSTGRES_HOST")
_pg_db = os.getenv("POSTGRES_DB")

if _pg_host and _pg_db:
    # PostgreSQL env vars set - use them (CI with service container)
    logger.info("Using PostgreSQL from environment variables")
    set_database(
        _pg_db,
        _pg_host,
        int(os.getenv("POSTGRES_PORT", "5432")),
        os.getenv("POSTGRES_USER", "herdbook"),
        os.getenv("POSTGRES_PASSWORD", ""),
    )
elif "pytest" in sys.modules or "unittest" in sys.modules:
    logger.info("No settings for database, using test database")
    set_test_database("herdbook")
else:
    logger.info("Using database per settings")

    set_database(
        settings.postgres.name,
        settings.postgres.host,
        settings.postgres.port,
        settings.postgres.user,
        settings.postgres.password,
    )


def connect():
    """
    Connects to the database if it isn't already connected.
    """
    if DATABASE and DATABASE.is_closed():
        try:
            DATABASE.connect()
            check_migrations()
        except OperationalError as exception:
            logger.error(exception)


def is_connected():
    """
    Wrapper around `DATABASE.is_connection_usable()`.
    """
    if not DATABASE:
        return False
    return DATABASE.is_connection_usable()


@contextmanager
def snapshot_read():
    """Read from one snapshot. An existing transaction owns its isolation level."""
    nested = DB_PROXY.in_transaction()
    with DB_PROXY.atomic():
        if not nested and isinstance(DATABASE, PostgresqlDatabase):
            DB_PROXY.execute_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield


class BaseModel(Model):
    """
    Base model for the herdbook database.

    This class sets the database to use the postgres database.
    """

    def as_dict(self):
        """
        Returns the objects key/value pair as a dictionary.
        """
        data = self.__dict__["__data__"].copy()
        for key, value in data.items():
            if value and key.endswith("_date"):
                data[key] = value.strftime("%Y-%m-%d")

        return data

    class Meta:  # pylint: disable=too-few-public-methods
        """
        The Meta class is read automatically for Model information.
        """

        database = DB_PROXY


class TimestampTZField(DateTimeField):
    """DateTimeField stored as TIMESTAMPTZ. Compare only with aware datetimes (datetime.now(timezone.utc))."""

    field_type = "TIMESTAMPTZ"


class Genebank(BaseModel):
    """
    Table for Genebanks.

    This table keep tracks of the names of genebanks.
    A genebank is comprised of several herds of animals.
    """

    id = AutoField(primary_key=True, column_name="genebank_id")
    name = CharField(100, unique=True)

    def short_info(self):
        """
        Returns the genebank data, including `id`, `name`, and a `herds` array
        including the `Herd.short_info()` data.
        """

        return {
            "id": self.id,
            "name": self.name,
            "herds": [h.short_info() for h in Herd.select().where(Herd.genebank == self)],
        }

    @snapshot_read()
    def get_herds(self, user):
        """
        Returns all herds that the user identified by `user` has access to,
        with restricted fields filtered by access level.
        Call outside a transaction to read from a dedicated snapshot.
        """
        if self.id not in user.accessible_genebanks:
            return None

        from utils.herd_contact import (  # pylint: disable=import-outside-toplevel
            herd_contacts,
            matrikel_reader_herd_ids,
        )

        account = (Membership.id, Membership.bank_account_number, Membership.bank_name)  # for filtered_dict
        rows = list(Herd.select(Herd, *account).join(Membership, JOIN.LEFT_OUTER).where(Herd.genebank == self))
        contacts = herd_contacts(rows)
        readers = matrikel_reader_herd_ids(user, rows)
        return [h.filtered_dict(user, contact=contacts[h.id], reader=h.id in readers, with_contact=False) for h in rows]


# The optional billing address, the same columns on Membership and
# MemberApplication (approval copies them over). All empty means the invoice
# goes to the postal address.
BILLING_FIELDS = (
    "billing_name",
    "billing_address",
    "billing_postal_code",
    "billing_city",
    "billing_email",
    "billing_reference",
)


class Membership(BaseModel):
    """
    Association-level membership (Member Model v2): the durable business
    entity — member number, status, postal address, publication consent,
    payment note. One row per matrikel Nr; person rows live in `member`.
    """

    id = AutoField(primary_key=True, column_name="membership_id")
    # NULL for friexemplar rows; unique WHERE NOT NULL (raw-SQL partial index).
    member_number = IntegerField(null=True)
    # CHECK-constrained: active | inactive | pending | friexemplar
    membership_status = CharField(max_length=20, default="active")
    organization_name = CharField(max_length=200, null=True)
    organization_number = CharField(max_length=11, null=True)
    address = TextField(null=True)
    # Structured postal address. The paper matrikel's single
    # "Postadress" column is derived — see the postal_address property.
    postal_code = CharField(max_length=10, null=True)
    city = CharField(max_length=100, null=True)
    publication_consent = BinaryJSONField(default=dict)
    # Free text from paper column "Bet senast" until phase 8-6 invoicing.
    payment_note = TextField(null=True)
    joined_date = DateField(default=date.today)
    notes = TextField(null=True)
    # Where the membership fee invoice goes when it is not the postal address:
    # a zoo, an association, a farm, a parent or a company. One per membership,
    # because the household pays one fee. See BILLING_FIELDS and invoice_address.
    billing_name = CharField(max_length=200, null=True)
    billing_address = TextField(null=True)
    billing_postal_code = CharField(max_length=10, null=True)
    billing_city = CharField(max_length=100, null=True)
    billing_email = CharField(max_length=255, null=True)
    billing_reference = CharField(max_length=100, null=True)
    # The account the genebank support is paid to (migration 58 moved it here from the herds), always private.
    # The type is NULL for an account moved from a herd: the old free text does not tell (CHECK: ACCOUNT_TYPES).
    bank_account_type = CharField(max_length=10, null=True)
    bank_account_number = TextField(null=True)
    bank_name = TextField(null=True)
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "membership"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    @property
    def postal_address(self) -> str | None:
        """Derived paper-matrikel 'Postadress' ("623 55 Visby") — READ-ONLY.
        The column was dropped by migrate_28_to_29; every serializer derives
        it from postal_code + city."""
        return format_postal_address(self.postal_code, self.city)

    @property
    def invoice_address(self) -> dict:
        """Where the membership fee invoice goes. Export and invoicing read this,
        never the billing columns one by one.

        Street, postal code and city come from the billing address as soon as
        one of them is set, otherwise all three from the postal address: an
        invoice never gets a billing street with the postal city. Without a
        billing name, the recipient is the organization name for a legal entity
        or None for the main member. An unset e-mail means the main member's
        own e-mail. The reference is returned as stored.
        """
        billing = any((self.billing_address, self.billing_postal_code, self.billing_city))
        return {
            "name": self.billing_name or self.organization_name,
            "address": self.billing_address if billing else self.address,
            "postal_code": self.billing_postal_code if billing else self.postal_code,
            "city": self.billing_city if billing else self.city,
            "email": self.billing_email,
            "reference": self.billing_reference,
        }


class MemberNumberCounter(BaseModel):
    """
    Single-row high-water mark for the member-number series (Member Model
    v2). Seeded by _seed_member_number_counter(); allocation locks this row
    with SELECT ... FOR UPDATE (utils/matrikel.py).
    """

    id = AutoField(primary_key=True, column_name="member_number_counter_id")
    value = IntegerField(null=False, default=0)

    class Meta:
        table_name = "member_number_counter"


class Herd(BaseModel):
    """
    Table for keeping track of herds.
    A herd is part of a genebank, and contains individuals.

    The herd table only holds herd information.
    Tracking of individuals over time is done in
    the herd_tracking table.

    Latitude/longitude in WGS84.
    Location should be a place name.

    *_privacy fields are enums with the values 'private', 'authenticated', and
    'public'.
    """

    id = AutoField(primary_key=True, column_name="herd_id")
    genebank = ForeignKeyField(Genebank)
    # v2: the herd is owned by an association membership; NULL until the
    # owner exists in the digital matrikel (Member Model v2 spec).
    membership = ForeignKeyField(Membership, null=True, backref="herds")
    herd = CharField(10)
    herd_name = TextField(null=True)
    is_active = BooleanField(null=True, default=False)
    start_date = DateField(null=True)
    name = TextField(null=True)
    name_privacy = CharField(15, null=True)
    physical_address = TextField(null=True)
    physical_address_privacy = CharField(15, null=True)
    location = TextField(null=True)
    location_privacy = CharField(15, null=True)
    email = TextField(null=True)
    email_privacy = CharField(15, null=True)
    email_verified = DateField(null=True)
    www = TextField(null=True)
    www_privacy = CharField(15, null=True)
    mobile_phone = TextField(null=True)
    mobile_phone_privacy = CharField(15, null=True)
    wire_phone = TextField(null=True)
    wire_phone_privacy = CharField(15, null=True)
    latitude = FloatField(null=True)
    longitude = FloatField(null=True)
    coordinates_privacy = CharField(15, null=True)
    # Empty since migration 58 (CHECK): the account is the membership's. The legacy API keeps the field names.
    bank_account_number = TextField(null=True)
    bank_account_number_privacy = CharField(15, null=True, default="private")
    bank_name = TextField(null=True)
    bank_name_privacy = CharField(15, null=True, default="private")
    # Contact from the member register (#117). contact_member is the person whose details the herd shows;
    # its FK constraint is added after both tables exist (see init and migrate_49_to_50).
    contact_member = DeferredForeignKey("Member", null=True, on_delete="SET NULL")
    # NULL: not compared with the register yet. A list: compared, holding the rows waiting for an answer.
    contact_pending = BinaryJSONField(null=True)

    def as_dict(self):
        """The row as a dict, without the contact plumbing (contact_member, contact_pending)."""
        data = super().as_dict()
        data.pop("contact_member", None)
        data.pop("contact_pending", None)
        return data

    def short_info(self):
        """
        Returns the `id`, `herd`, `genebank`, `herd_name`, and `is_active`
        fields as a dict.
        """
        return {
            "id": self.id,
            "herd": self.herd,
            "genebank": self.__dict__["__data__"]["genebank"],
            "herd_name": self.herd_name,
            "is_active": self.is_active,
        }

    def filtered_dict(self, user=None, *, contact=None, reader=None, with_contact=True):
        """
        Returns the model data filtered by the access level of the given `user`.

        The contact rows are the resolved ones (#117). `contact` and `reader` can be given when the caller
        has them for many herds at once; `with_contact` adds the `contact` field to the answer.
        Load the herd in the same snapshot as its contact data, or under lock_herd when writing.
        """
        from utils.herd_contact import (  # pylint: disable=import-outside-toplevel
            contact_field,
            herd_contact,
            is_matrikel_reader,
        )

        access_level = "public"
        if user and user.is_admin:
            access_level = "private"
        elif user:
            for role in user.privileges:
                if role["level"] in ["viewer", "manager"] and role["genebank"] == self.genebank.id:
                    # Every new account is a viewer of both genebanks (OAuth
                    # autocreate, add_user), so a viewer reads like any other
                    # member: 'private' ("Endast genbanksansvarig") is for the
                    # genebank's manager, admin and the herd's own users.
                    access_level = "authenticated"
                    if role["level"] == "manager":
                        access_level = "private"
                        break
            if access_level != "private":
                # Effective herd access (Member Model v2): legacy owner
                # privileges, derived main-member ownership and active
                # grants all land here — a grant-only caretaker must see
                # the herd exactly like an owner would.
                effective = user.effective_herd_ids()
                if self.id in effective:
                    access_level = "private"
                elif effective:
                    access_level = "authenticated"

        data = self.as_dict()

        if "email_verified" in data:
            del data["email_verified"]
        # membership is v2-internal ownership plumbing — keep it out of the
        # legacy herd response (ADR-0006: don't perturb legacy contracts).
        data.pop("membership", None)

        contact = contact or herd_contact(self)
        reader = is_matrikel_reader(user, self) if reader is None else reader
        raw = data
        data = remove_fields_by_privacy(raw, access_level)
        # fetched rows: the register's value in the same field, seen by a matrikel reader at "private" and
        # by anyone else at most at "authenticated" (decision 11); own rows are filtered as above
        derived = {f: r.value for f, r in contact.rows.items() if r.source != "egen"}
        if derived:
            levels = list(PRIVACY_LEVELS)
            level = "private" if reader else min(access_level, "authenticated", key=levels.index)
            shown = remove_fields_by_privacy({**raw, **derived}, level)
            for field, value in derived.items():
                if field in shown:
                    data[field] = value
                else:
                    data.pop(field, None)
        # The support account is the membership's (migration 58), under the herd's legacy field names: its end and
        # bank for admin, matrikel_admin (who has no genebank role, so only these fields are added, not the other
        # private ones), the genebank's manager and the herd's owners; nothing for a caretaker grant (U2) or another
        # member. Never the whole number: the old app sends back what it read, and update_herd takes only a mask that
        # is still the stored account's as an unchanged account, so a stale form cannot write an old one back.
        for field in HERD_BANK_FIELDS:
            data.pop(field, None)
        if user and (
            user.is_admin
            or user.is_matrikel_admin
            or (
                access_level == "private"
                and (self.genebank_id in (user.is_manager or ()) or self.id in user.transfer_herd_ids())
            )
        ):
            membership = self.membership if self.membership_id else None
            number, name = (membership.bank_account_number, membership.bank_name) if membership else (None, None)
            account = {"bank_account_number": account_end(number), "bank_name": name}
            data.update({field: value for field, value in account.items() if field in raw})  # the row's keys, as before
        if with_contact and user:
            field = contact_field(user, self, contact, reader=reader, private_access=access_level == "private")
            if field:
                data["contact"] = field
        return data

    class Meta:  # pylint: disable=too-few-public-methods
        """
        Add a unique index to herd+genebank
        """

        indexes = ((("herd", "genebank"), True),)


# The herd's own contact values: kept out of audit snapshots, so the register can retire them (#117).
HERD_CONTACT_COLUMNS = ("name", "email", "mobile_phone", "wire_phone", "physical_address", "www")

PRIVACY_LEVELS = ("public", "authenticated", "private")

# The bank details are only for support payouts: never shown to other members,
# whatever the stored level says (issue #33).
BANK_PRIVACY_FIELDS = ("bank_account_number_privacy", "bank_name_privacy")
# The herd's old account columns, empty since migration 58, and the support account's types (Jonas 2026-11-18).
HERD_BANK_FIELDS = ("bank_account_number", "bank_name")
ACCOUNT_TYPES = ("bankkonto", "bankgiro", "plusgiro")


ACCOUNT_MASK = "••"


def account_end(value):
    """
    Only the last two digits of a bank account number, for readers who must not see all of it. Under five digits the
    two would give most of it away (a plusgiro may have two): then only the mask, which says there is one.

    >>> account_end("8327-9, 123 456 789 12")
    '••12'
    >>> account_end("123-4")
    '••'
    >>> account_end(None) is None
    True
    """
    if not value:
        return value
    digits = re.sub(r"\D", "", str(value))
    return ACCOUNT_MASK + (digits[-2:] if len(digits) >= 5 else "")


def remove_fields_by_privacy(data, access_level):
    """
    Removes fields according to a given access level (private, authenticated
    or public) by looking at the _privacy fields in the data.

    >>> test_data = {
    ...     'high': 3,
    ...     'high_privacy': 'private',
    ...     'mid': 4,
    ...     'mid_privacy': 'authenticated',
    ...     'low': 5,
    ...     'low_privacy': 'public',
    ... }
    >>> remove_fields_by_privacy(test_data, 'private') == test_data
    True
    >>> remove_fields_by_privacy(test_data, 'authenticated')
    {'mid': 4, 'low': 5}
    >>> remove_fields_by_privacy(test_data, 'public')
    {'low': 5}

    The bank details are always private, whatever level is stored.

    >>> test_data = {
    ...     'bank_name': 'B',
    ...     'bank_name_privacy': 'public',
    ... }
    >>> remove_fields_by_privacy(test_data, 'public')
    {}

    The privacy level of the fields 'latitude' and 'longitude' are
    under 'coordinates_privacy'.

    >>> test_data = {
    ...     'coordinates_privacy': 'authenticated',
    ...     'latitude': 59,
    ...     'longitude': 17,
    ... }
    >>> remove_fields_by_privacy(test_data, 'authenticated')
    {'latitude': 59, 'longitude': 17}
    >>> remove_fields_by_privacy(test_data, 'public')
    {}

    """

    data = {**data}

    levels = list(PRIVACY_LEVELS)
    # prune data according to access level
    for field in [f for f in data.keys() if f.endswith("_privacy")]:
        # remove values if access_level is less than required
        field_level = data[field] or "private"
        if field_level not in levels:  # unknown stored value: fail closed instead of raising
            field_level = "private"
        if levels.index(access_level) < levels.index(field_level):
            if field == "coordinates_privacy":
                if "latitude" in data:
                    del data["latitude"]
                if "longitude" in data:
                    del data["longitude"]
            else:
                target_field = field[: -len("_privacy")]
                if target_field in data:
                    del data[target_field]
        # remove the access level value if the user doesn't have private access
        if access_level != "private":
            del data[field]

    # Bank details: only for private access, whatever the stored level says (issue #33). Dropped
    # here and not via the *_privacy keys, so a row loaded without them cannot let them through.
    if access_level != "private":
        data.pop("bank_account_number", None)
        data.pop("bank_name", None)

    return data


class Color(BaseModel):
    """
    Table for colors.

    This table keep tracks of the available color types of animals.
    """

    id = AutoField(primary_key=True, column_name="color_id")
    name = CharField(50)
    comment = CharField(100, null=True)
    genebank = ForeignKeyField(Genebank)


class Breeding(BaseModel):
    """
    Table for breeding and birth.
    breeding_herd_id is the herd the mother existed in when she gave birth
    litter_size6w is a field to store how many litter was alive 6 weeks after birth.
    If all litter of a breed exists as individuals in the herdbook we can calculate this
    but probably we need to store this for users that are only adding registered animals.
    """

    id = AutoField(primary_key=True, column_name="breeding_id")
    breeding_herd_id = ForeignKeyField(Herd)
    breed_date = DateField(null=True)
    breed_notes = TextField(null=True)
    father = DeferredForeignKey("Individual", null=True)
    mother = DeferredForeignKey("Individual", null=True)
    birth_date = DateField(null=True)
    birth_notes = TextField(null=True)
    litter_size = IntegerField(null=True)
    litter_size6w = IntegerField(null=True)
    litter_number = SmallIntegerField(null=True)
    # litter_size6w is prefilled with litter_size and not yet confirmed (yearly report, step 4)
    litter_size6w_preliminary = BooleanField(default=False, constraints=[SQL("DEFAULT false")])
    updated_at = DateTimeField(default=datetime.now, null=True)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    def as_dict(self):
        """
        Returns the objects key/value pair as a dictionary.

        The parent foreign keys are also replaced by parent numbers, as they
        frontend uses parent numbers instead of database id's.
        """
        data = super().as_dict()
        # pylint: disable=no-member
        data["mother"] = self.mother.number if self.mother else None
        data["father"] = self.father.number if self.father else None
        data["mother_name"] = self.mother.name if self.mother else None
        data["father_name"] = self.father.name if self.father else None
        data["breeding_herd"] = self.breeding_herd_id.herd if self.breeding_herd_id else None
        data.pop("updated_at", None)
        return data

    class Meta:  # pylint: disable=too-few-public-methods
        """
        Add a unique index to mother+father+birth_date
        """

        indexes = ((("mother", "father", "birth_date"), True),)


def next_individual_number(herd, birth_date, breeding_event):
    """
    Returns the number for the next individual in a litter for a
    given year and herd.

    The stored ``Breeding.litter_number`` is the single source of truth for
    the litter component — the computed chronological rank is only a fallback for
    legacy rows where it is still NULL. This function is a pure read/compute; the
    caller (``add_individual``/promotion) holds the ``Breeding … FOR UPDATE`` lock
    across the subsequent insert so the minted number can't collide.
    """
    if isinstance(birth_date, str):
        birth_date = datetime.strptime(birth_date, "%Y-%m-%d")
        assert isinstance(birth_date, datetime)
    try:
        try:
            breeding_row = Breeding.get_by_id(breeding_event)
        except Breeding.DoesNotExist:
            # Legacy asks for the next number BEFORE the breeding exists (the
            # "new litter" branch sends no id at all), so a missing event is not
            # an error — fall through to the chronological-rank fallback, which
            # ranks the coming litter as len(events) + 1 exactly as the old
            # backend did.
            breeding_row = None

        if breeding_row is not None and breeding_row.litter_number is not None:
            # Stored litter number wins.
            litter_number = breeding_row.litter_number
            real_litter_size = breeding_row.litter_size or 0
        else:
            # Fallback: compute the chronological rank for legacy NULL rows.
            herd_id = Herd.get(Herd.herd == herd)
            rank_expr = fn.ROW_NUMBER().over(
                order_by=[
                    fn.COALESCE(
                        Breeding.birth_date,
                        Breeding.breed_date + 30,
                    ),
                    Breeding.id,
                ]
            )
            events = (
                Breeding.select(
                    rank_expr.alias("litter_number"),
                    Breeding.id,
                    Breeding.litter_size,
                )
                .where(Breeding.breeding_herd_id == herd_id)
                .where(
                    DATABASE.extract_date(
                        "year",
                        fn.COALESCE(Breeding.birth_date, Breeding.breed_date),
                    )
                    == birth_date.year
                )
            )
            ev = events.execute()
            if len(ev) == 0:
                litter_number = 1
                real_litter_size = 0
            else:
                query = (
                    Select(columns=[events.c.litter_number, events.c.litter_size])
                    .from_(events)
                    .where(events.c.breeding_id == breeding_event)
                    .bind(DATABASE)
                ).execute()
                if len(query) == 0:
                    litter_number = len(ev) + 1
                    real_litter_size = 0
                else:
                    litter_number = query[0].get("litter_number")
                    real_litter_size = query[0].get("litter_size") if query[0].get("litter_size") else 0

        if real_litter_size == 0:
            number_in_kull = 1
        else:
            # Existing siblings (incl. voided ones, which keep their number) are
            # parsed so a retired slot is never reissued; voided rows also count
            # against the cap, matching _get_litter_state's (used ∪ retired) rule.
            individuals = (Individual.select(Individual.number).where(Individual.breeding == breeding_event)).execute()
            litter_size = len(individuals)
            if litter_size >= real_litter_size:
                return {
                    "status": "error",
                    "message": "litter_size",
                    "number": None,
                }
            elif litter_size == 9:
                return {
                    "status": "error",
                    "message": "NINE",
                    "number": None,
                }
            else:
                litter_number_list = list()
                for ind in individuals:
                    try:
                        indnumber = int(ind.number.split(f"{herd}-{str(birth_date.year)[2:4]}{litter_number}")[-1])
                    except ValueError:
                        return {
                            "status": "error",
                            "message": "kull",
                            "kull": litter_number,
                            "wrong": ind.number,
                            "number": f"{herd}-{str(birth_date.year)[2:4]}{litter_number}{1}",
                        }
                    litter_number_list.append(indnumber)
                litter_number_list.sort()
                try:
                    number_in_kull = sorted(
                        set(range(1, min(real_litter_size + 1, 10))).difference(litter_number_list)
                    )[0]
                except IndexError:
                    if litter_size >= real_litter_size and real_litter_size <= 9:
                        return {
                            "status": "error",
                            "message": "litter_size",
                            "number": None,
                        }
                    else:
                        return {
                            "status": "error",
                            "message": "NINE",
                            "number": None,
                        }

        ind_number = f"{herd}-{str(birth_date.year)[2:4]}{litter_number}{number_in_kull}"

        return {
            "status": "success",
            "message": "ledigt nummer hittat",
            "number": ind_number,
        }

    except Exception as exception:
        logger.error(exception)
        return {"status": "error", "message": exception, "number": None}


class Individual(BaseModel):
    """
    Table for individual animals.

    The sex is an enum with the values 'male', 'female', and 'eunuch'.
    """

    id = AutoField(primary_key=True, column_name="individual_id")
    origin_herd = ForeignKeyField(Herd)
    name = CharField(50, null=True)
    certificate = CharField(20, unique=True, null=True)
    digital_certificate = IntegerField(unique=True, null=True)
    foot_ring = CharField(20, null=True)
    # ISO 11784: 15 digits, Swedish chips start with 752. Empty is NULL.
    microchip = CharField(15, null=True, constraints=[Check("microchip ~ '^[0-9]{15}$'")])
    number = CharField(20, unique=True)
    sex = CharField(15, null=True)
    color = ForeignKeyField(Color, null=True)
    color_note = TextField(null=True)
    death_date = DateField(null=True)
    death_note = TextField(null=True)
    notes = TextField(null=True)
    breeding = ForeignKeyField(Breeding, null=True)
    eye_color = TextField(null=True)
    claw_color = TextField(null=True)
    belly_color = TextField(null=True)
    hair_notes = TextField(null=True)
    rex = BooleanField(default=False, constraints=[SQL("DEFAULT false")])  # the coat: rex, else normal
    is_active = BooleanField(null=True, default=True)
    has_photo = BooleanField(null=True, default=False)
    butchered = BooleanField(null=True, default=False)
    castration_date = DateField(null=True, default=None)
    voided = BooleanField(default=False)
    voided_at = DateTimeField(null=True)
    updated_at = DateTimeField(default=datetime.now, null=True)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        if self.id is not None:
            return super().save(*args, **kwargs)
        # Here, so that every way a rabbit is created wakes the intake queue's items waiting for it, in one
        # transaction with the insert even when the caller has none.
        from utils.inbox import parent_registered  # pylint: disable=import-outside-toplevel  # it imports us

        with DB_PROXY.atomic():
            saved = super().save(*args, **kwargs)
            parent_registered(self.number)
        return saved

    @property
    def current_herd(self):
        """
        Returns the current herd of the individual by querying the HerdTracking
        table.
        """

        latest_ht_entry = self.latest_herdtracking_entry
        if latest_ht_entry:
            return latest_ht_entry.herd

        # Individual not found in HerdTracking!
        return self.origin_herd

    @property
    def latest_herdtracking_entry(self):
        """The latest ACTIVE herd-tracking row, or None."""
        return current_holder_row(self.id)

    @property
    def children(self):
        """
        Returns a list of the individuals registered children.
        """
        # use a list comprehension to execute the query and return the result
        # as a list.
        # pylint: disable=unnecessary-comprehension
        return [
            i
            for i in Individual.select()
            .join(Breeding)
            .where((Breeding.mother == self) | (Breeding.father == self))
            .where(not_voided())
        ]

    @property
    def active(self):
        """
        Active = registered, alive, not castrated, a life sign (BIRTH/TRANSFER/
        ATTESTATION) within ACTIVE_WINDOW_DAYS, and held by an active in-genebank herd.
        """
        herd = self.current_herd
        life_sign = latest_life_sign_date(self.id)
        cutoff = (datetime.now() - timedelta(days=ACTIVE_WINDOW_DAYS)).date()
        return bool(
            herd.is_active
            and herd.herd not in OUTSIDE_GENEBANK_HERDS
            and not self.death_date
            and not self.death_note
            and not self.castration_date
            and (self.certificate or self.digital_certificate)
            and life_sign is not None
            and coerce_date(life_sign) > cutoff
        )

    @property
    def alive(self):
        """
        Returns if an indivdual is alive
        """
        is_alive = not self.death_date and not self.death_note
        return is_alive

    def cert_state(self):
        """The certificate state (utils/certificate_lifecycle.py) of this instance's columns and the stored rows."""
        current = DigitalCertificateV2.select().where(
            DigitalCertificateV2.individual == self.id, DigitalCertificateV2.is_current
        )
        try:
            return state_of(self.certificate, self.digital_certificate, current.exists())
        except ValueError:
            # No state allows it: both numbers (the old backend), or a current PDF row whose number was lost
            # (migrate_37_to_38 leaves those). check() does not judge a writer that starts here.
            return None

    def as_dict(self):
        """
        Returns the objects key/value pair as a dictionary, including data from
        the weight, color, and bodyfat tables.
        """
        data = super().as_dict()
        data["genebank_id"] = self.current_herd.genebank.id
        data["is_active"] = self.active
        data["is_registered"] = bool(self.certificate or self.digital_certificate)
        data["genebank"] = self.current_herd.genebank.name
        data["origin_herd"] = {
            "id": self.origin_herd.id,
            "herd": self.origin_herd.herd,
            "herd_name": self.origin_herd.herd_name,
        }
        data["herd"] = {
            "id": self.current_herd.id,
            "herd": self.current_herd.herd,
            "herd_name": self.current_herd.herd_name,
        }
        data["alive"] = self.alive
        data["birth_date"] = self.breeding.birth_date.strftime("%Y-%m-%d") if self.breeding.birth_date else None
        data["litter_size"] = self.breeding.litter_size if self.breeding else None
        data["litter_size6w"] = self.breeding.litter_size6w if self.breeding else None

        data["mother"] = (
            {
                "id": self.breeding.mother.id,
                "name": self.breeding.mother.name,
                "number": self.breeding.mother.number,
            }
            if self.breeding and self.breeding.mother
            else {
                "id": None,
                "name": None,
                "number": None,
            }
        )
        data["father"] = (
            {
                "id": self.breeding.father.id,
                "name": self.breeding.father.name,
                "number": self.breeding.father.number,
            }
            if self.breeding and self.breeding.father
            else {
                "id": None,
                "name": None,
                "number": None,
            }
        )
        data["color"] = self.color.name if self.color else None
        data["color_id"] = self.color_id
        data["weights"] = [{"weight": w.weight, "date": w.weight_date.strftime("%Y-%m-%d")} for w in self.weight_set]  # pylint: disable=no-member
        data["bodyfat"] = [
            {"bodyfat": b.bodyfat, "date": b.bodyfat_date.strftime("%Y-%m-%d")} for b in self.bodyfat_set
        ]

        # Use prefetched herd tracking data if available, otherwise query it
        if hasattr(self, "herd_tracking_set"):
            data["herd_tracking"] = self.herd_tracking_set
        else:
            ht_history = (
                HerdTracking.select()
                .where(HerdTracking.individual == self.id, ht_not_voided())
                .order_by(*ht_order_desc())
            )

            try:
                data["herd_tracking"] = [
                    {
                        "herd_id": h.herd.id,
                        "herd": h.herd.herd,
                        "herd_name": h.herd.herd_name,
                        "date": (h.herd_tracking_date.strftime("%Y-%m-%d") if h.herd_tracking_date else None),
                        "kind": h.kind,
                    }
                    for h in ht_history
                ]
            except DoesNotExist:
                data["herd_tracking"] = []

        data.pop("updated_at", None)
        return data

    def list_info(self):
        """
        Returns the information that is to be viewed in the main individuals
        table.
        """
        data = super().as_dict()
        data.pop("updated_at", None)
        return data

    def short_info(self):
        """
        Returns a dictionary with a subset of fields so that all data doesn't
        have to be sent when rendering tables.
        Included fields.
            - id
            - name
            - number
            - sex
            - father
            - mother
        """
        father = (
            {
                "id": self.breeding.father.id,
                "number": self.breeding.father.number,
            }
            if self.breeding and self.breeding.father
            else None
        )
        mother = (
            {
                "id": self.breeding.mother.id,
                "number": self.breeding.mother.number,
            }
            if self.breeding and self.breeding.mother
            else None
        )

        return {
            "id": self.id,
            "name": self.name,
            "number": self.number,
            "sex": self.sex,
            "father": father,
            "mother": mother,
            "is_active": self.active,
        }

    class Meta:  # pylint: disable=too-few-public-methods
        """
        Add a unique index to number+genebank
        """

        indexes = ((("number", "origin_herd"), True),)


def not_voided(model=Individual):
    """
    Peewee filter expression excluding soft-voided individuals (unpromoted
    litter slots). Pass an Individual alias to filter aliased queries.
    """
    return model.voided == False  # noqa: E712 — peewee ORM requires == not `is`


class Bunny(BaseModel):
    """
    Roster slot for a bunny in a litter.

    Each Bunny belongs to a Breeding (litter) and occupies a slot_order
    position.  When a bunny is registered in the studbook its fate becomes
    'registered' and the individual FK is set — enforced by the DB CHECK
    constraint so the invariant is upheld on every save path.
    """

    id = AutoField(primary_key=True, column_name="bunny_id")
    breeding = ForeignKeyField(Breeding, backref="bunnies", on_delete="RESTRICT")
    slot_order = IntegerField()
    label = CharField(40, null=True)
    observed_sex = CharField(15, null=True)
    observed_color = CharField(60, null=True)
    fate = CharField(20, default="undecided")
    individual = ForeignKeyField(Individual, null=True, unique=True, backref="bunny")
    notes = TextField(null=True)
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    def as_dict(self):
        """
        Returns roster fields.  Linked bunnies include individual.short_info();
        unlinked bunnies include observed_sex and observed_color instead.
        """
        base = {
            "id": self.id,
            "breeding_id": self.breeding_id,
            "slot_order": self.slot_order,
            "label": self.label,
            "fate": self.fate,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if self.individual_id is not None:
            return {**base, "individual": self.individual.short_info()}
        return {**base, "observed_sex": self.observed_sex, "observed_color": self.observed_color}

    class Meta:  # pylint: disable=too-few-public-methods
        """Enforce fate='registered' ⟺ individual link is set."""

        constraints = [Check("(fate = 'registered') = (individual_id IS NOT NULL)")]


class IndividualFile(BaseModel):
    """
    Table for referencing files connected to individuals
    """

    id = AutoField(primary_key=True, column_name="breeding_id")
    individual = ForeignKeyField(Individual)
    filepath = CharField(32)
    upload_name = CharField(128)
    notes = TextField()


class Disease(BaseModel):
    """
    Lists user defined diseases, and keeps track of wheather they should be
    included in the yearly report.
    """

    id = AutoField(primary_key=True, column_name="disease_id")
    name = CharField()
    include_in_reports = BooleanField(default=False)


class IndividualDisease(BaseModel):
    """
    Kepps track of disease periods for individuals.
    """

    id = AutoField(primary_key=True, column_name="individual_disease_id")
    individual = ForeignKeyField(Individual)
    disease = ForeignKeyField(Disease)
    diagnosis_date = DateField()
    healthy_date = DateField()
    notes = TextField()


class Weight(BaseModel):
    """
    Table for tracking animal weights.
    """

    id = AutoField(primary_key=True, column_name="weight_id")
    individual = ForeignKeyField(Individual)
    weight = FloatField()
    weight_date = DateField()


class Bodyfat(BaseModel):
    """
    Table for keeping track of animal body fat types.
    The available types are: 'low', 'normal', and 'high'
    """

    id = AutoField(primary_key=True, column_name="bodyfat_id")
    individual = ForeignKeyField(Individual)
    bodyfat = CharField(6, null=True)
    bodyfat_date = DateField()


class AccountRulesSnapshot(BaseModel):
    sha256 = TextField(primary_key=True)
    text = TextField()
    cms_version = TextField()
    first_accepted_at = TimestampTZField()

    class Meta:
        table_name = "account_rules_snapshot"


class User(BaseModel, UserMixin):
    """
    Table keeping track of system users.
    """

    id = AutoField(primary_key=True, column_name="user_id")
    username = TextField(unique=True, null=True)
    email = TextField()
    fullname = TextField(null=True)
    uuid = UUIDField()
    validated = BooleanField(default=False)
    _privileges = TextField(column_name="privileges", default="[]")
    last_active = DateTimeField(default=datetime.now)
    # Profile picture fields
    profile_picture = TextField(null=True)  # Custom uploaded picture path
    google_picture = TextField(null=True)  # Google profile picture URL
    google_name = TextField(null=True)  # Google display name
    google_email = TextField(null=True)  # Google email
    use_google_picture = BooleanField(default=True)  # User preference
    # Additive column for per-user v2-prod promotion; never read by legacy.
    v2_prod_access = BooleanField(default=False)
    rules_accepted_at = TimestampTZField(null=True)
    rules_version = TextField(null=True)
    rules_snapshot = ForeignKeyField(AccountRulesSnapshot, column_name="rules_sha256", null=True, index=False)
    # Phase 17 — account deactivation. Peewee's FieldAccessor shadows
    # flask_login UserMixin.is_active (same pattern as Herd.is_active), so
    # login_user() natively refuses inactive users. Normal audited column —
    # flag flips MUST produce audit rows, so NOT change_detection_excluded.
    is_active = BooleanField(default=True)
    # The person's own choice to show her full name as "Intygas av" on the public certificate check page
    # (stamboken #6). NULL = not chosen yet (every new account), shown as not chosen. Only she sets it, through its
    # own endpoint; anonymisation switches it off.
    name_on_check_page = BooleanField(null=True)

    def update_last_active(self):
        self.last_active = datetime.now()
        # One column: this row was read at request start, so a full-row save
        # would write back a stale is_active/_privileges.
        self.save(only=[User.last_active])

    @property
    def privileges(self):
        """
        Wrapper property to convert a json text string to a python object.
        The privileges are a list of roles, formatted as:
        [
            {'level': 'admin'} |
            {'level': 'viewer' | 'manager' | 'helper', 'genebank': id} |
            {'level': 'owner', 'herd': id}
        ]
        """
        try:
            return json.loads(self._privileges)
        except json.JSONDecodeError:
            logger.error("Couldn't load user privileges. Defaulting to None")
            return []

    @privileges.setter
    def privileges(self, value):
        """
        Set the _privileges field to a json string from a python object.
        """
        try:
            self._privileges = json.dumps(value)
        except json.JSONDecodeError:
            logger.error("Couldn't encode '%s' as json string", value)

    @privileges.deleter
    def privileges(self):
        """
        Resets the _privilege field to a list of empty roles.
        """
        self._privileges = json.dumps([])

    def add_role(self, level, target_id=None):
        """
        Add `level` with `target_id` to the user privilege list. Allowed
        level/target_id combinations are:
            - level: admin, (no target)
            - level: matrikel_admin, (no target)
            - level: viewer, genebank: target_id
            - level: manager, genebank: target_id
            - level: helper, genebank: target_id
            - level: owner, herd: target_id
        """

        privs = self.privileges
        if level not in ["admin", "viewer", "manager", "helper", "owner", "matrikel_admin"]:
            logger.error("Unknown role level %s", level)
            return
        role = {"level": level}
        if level in ["viewer", "manager", "helper"]:
            role["genebank"] = target_id
        elif level == "owner":
            role["herd"] = target_id
        privs += [role]
        self.privileges = privs
        self.save(only=[User._privileges])

    def has_role(self, level, target_id=None):
        """
        Check if role `level` with target `target_id` is in the user privilege
        list. Returns `True` or `False`.

        Allowed level/target_id combinations are:
            - level: admin, (no target)
            - level: matrikel_admin, (no target)
            - level: viewer, genebank: target_id
            - level: manager, genebank: target_id
            - level: helper, genebank: target_id
            - level: owner, herd: target_id
        """
        for role in self.privileges:
            if role["level"] == level:
                if level in ("admin", "matrikel_admin"):
                    return True
                if level in ["viewer", "manager", "helper"] and target_id == role["genebank"]:
                    return True
                if level == "owner" and target_id == role["herd"]:
                    return True
        return False

    def remove_role(self, level, target_id=None):
        """
        Check if role `level` with target `target_id` is in the user privilege
        list, and remove it if it is present.

        Allowed level/target_id combinations are:
            - level: admin, (no target)
            - level: matrikel_admin, (no target)
            - level: viewer, genebank: target_id
            - level: manager, genebank: target_id
            - level: helper, genebank: target_id
            - level: owner, herd: target_id
        """
        new_privs = []
        for role in self.privileges:
            if role["level"] == level:
                if level in ("admin", "matrikel_admin"):
                    continue
                if level in ["viewer", "manager", "helper"] and target_id == role["genebank"]:
                    continue
                if level == "owner" and target_id == role["herd"]:
                    continue
            new_privs += [role]
        self.privileges = new_privs
        self.save(only=[User._privileges])

    @property
    def is_admin(self):
        """
        Returns `True` if the admin permission is in the user privileges, false
        otherwise.
        """
        return "admin" in [p["level"] for p in self.privileges]

    @property
    def is_matrikel_admin(self):
        """
        Returns `True` if the matrikel_admin permission is in the user
        privileges, false otherwise. Registry-wide matrikel CRUD, no
        studbook rights (Member Model v2).
        """
        return "matrikel_admin" in [p["level"] for p in self.privileges]

    @property
    def is_manager(self):
        """
        Returns a list of id's of the genebanks that the user is manager of, or
        `None`.
        """
        genebanks = []
        for role in self.privileges:
            if role["level"] == "manager":
                genebanks += [role["genebank"]]
        return genebanks or None

    @property
    def is_helper(self):
        """
        The ids of the genebanks where the user is a genebank helper (genbankshjälpare), or `None`. A helper
        works in the intake queue and writes only through an item they have taken (utils.inbox.InboxGrant),
        never through can_edit.
        """
        return [role["genebank"] for role in self.privileges if role["level"] == "helper"] or None

    @property
    def is_owner(self):
        """
        Returns a list of herd codes (`Herd.herd`) for the herds the user
        effectively owns or may edit — grandfathered legacy owner
        privileges plus derived v2 access — or `None`. The
        list-of-strings-or-None shape is bound by ADR-0006 (/api/user).
        """
        herd_ids = self.effective_herd_ids()
        if not herd_ids:
            return None
        return [h.herd for h in Herd.select().where(Herd.id.in_(list(herd_ids))).order_by(Herd.id)]

    def _owned_herd_ids_and_persons(self):
        """
        Returns `(herd_ids, persons)`: the herd ids from rights (a) and (b) of
        `effective_herd_ids()` (legacy owner privilege entries and herds of
        memberships where the user is the active huvudmedlem), plus the user's
        active person rows (needed for grants). Shared by `effective_herd_ids`
        and `transfer_herd_ids` so the two cannot drift apart.
        """
        herd_ids = set()
        for role in self.privileges:
            if role["level"] == "owner":
                herd_ids.add(role["herd"])

        persons = list(
            Member.select(Member.id, Member.membership, Member.role)
            .join(Membership)
            .where(
                (Member.user == self.id) & Member.end_date.is_null(True) & (Membership.membership_status == "active")
            )
        )

        main_memberships = [p.membership_id for p in persons if p.role == "huvudmedlem" and p.membership_id]
        if main_memberships:
            for herd in Herd.select(Herd.id).where(Herd.membership.in_(main_memberships)):
                herd_ids.add(herd.id)

        return herd_ids, persons

    def effective_herd_ids(self):
        """
        Herd ids this user can edit — the single derivation of herd-level
        rights (Member Model v2), the union of:

        (a) grandfathered legacy {"level": "owner", "herd": id} privilege
            entries — kept working, but no longer written by auto-link;
        (b) herds owned by the membership where this user's active person
            row (end_date IS NULL) has role 'huvudmedlem';
        (c) herds of active grants (revoked_at IS NULL AND (valid_until
            IS NULL OR valid_until >= today)) held by active person rows.

        (b) and (c) additionally require membership_status = 'active': an
        inactive/retired (or pending/friexemplar) membership conveys no herd
        rights, so a plain status flip immediately suspends access without
        ending person rows — flipping back restores it.

        All permission/visibility consumers must route through this —
        never read the owner entries of the privileges JSON directly.

        EXCEPTION: herd/rabbit ownership TRANSFER (sell/move, the Phase 10
        flow) must NOT be gated on this union — transfer requires the
        membership's main member or a manager/admin. A caretaker holding a
        grant can edit the herd but must never be able to transfer or give
        it away. Use `can_transfer` / `transfer_herd_ids` for that.
        """
        herd_ids, persons = self._owned_herd_ids_and_persons()

        person_ids = [p.id for p in persons]
        if person_ids:
            today = date.today()
            active_grants = HerdAccessGrant.select(HerdAccessGrant.herd).where(
                HerdAccessGrant.member.in_(person_ids)
                & HerdAccessGrant.revoked_at.is_null(True)
                & (HerdAccessGrant.valid_until.is_null(True) | (HerdAccessGrant.valid_until >= today))
            )
            for grant in active_grants:
                herd_ids.add(grant.herd_id)

        return herd_ids

    def transfer_herd_ids(self):
        """
        Herd ids this user may transfer rabbits out of as an owner: rights (a)
        and (b) of `effective_herd_ids()` only — never herd-access grants (c).
        """
        return self._owned_herd_ids_and_persons()[0]

    def can_transfer(self, individual_id):
        """
        Returns `True` if the user may sell/move the individual with id
        `individual_id` to another herd: an admin, a manager of the
        individual's genebank, or the owner (legacy owner privilege or active
        huvudmedlem) of its CURRENT herd. Caretakers with a herd-access grant
        may edit but never transfer.
        """
        if self.is_admin:
            return True
        try:
            herd = Individual.get(Individual.id == individual_id).current_herd
        except DoesNotExist:
            return False
        if self.is_manager and herd.genebank_id in self.is_manager:
            return True
        if herd.herd in OUTSIDE_GENEBANK_HERDS:
            return False  # only managers/admin move a rabbit back into the genebank
        return herd.id in self.transfer_herd_ids()

    @property
    def accessible_genebanks(self):
        """
        Returns a list of all genebank id's that the user has access to.
        """
        if self.is_admin:
            return [g.id for g in Genebank(database=DATABASE).select()]
        has_access = []
        for role in self.privileges:
            if role["level"] in ["viewer", "manager", "helper"]:
                has_access += [role["genebank"]]
        herd_ids = self.effective_herd_ids()
        if herd_ids:
            for herd in Herd.select().where(Herd.id.in_(list(herd_ids))).order_by(Herd.id):
                if herd.genebank_id not in has_access:
                    has_access += [herd.genebank_id]
        return has_access

    def frontend_data(self):
        """
        Returns the information that is needed in the frontend.
        """
        return {
            "id": self.id,
            "email": self.email,
            "fullname": self.fullname,
            "username": self.username,
            "validated": self.validated if self.validated else False,
            "is_admin": self.is_admin,
            "is_matrikel_admin": self.is_matrikel_admin,
            "is_manager": self.is_manager,
            "is_owner": self.is_owner,
            # Profile picture data
            "profile_picture": self.profile_picture,
            "google_picture": self.google_picture,
            "google_name": self.google_name,
            "google_email": self.google_email,
            "use_google_picture": self.use_google_picture,
            "v2_prod_access": self.v2_promoted,
        }

    @property
    def v2_promoted(self):
        """
        Admins are implicitly promoted to v2 prod; the stored flag is the
        per-user promotion mechanism for everyone else (Phase 999.2).
        """
        return self.v2_prod_access or self.is_admin

    def get_genebanks(self):
        """
        Returns a list of all genebanks that the user has access to.
        """
        query = Genebank(database=DATABASE).select()

        if not self.is_admin:
            query = query.where(Genebank.id.in_(self.accessible_genebanks))

        # Using a list comprehension here will turn the iterator into a list
        return [g for g in query.execute()]  # pylint: disable=unnecessary-comprehension

    def get_genebank(self, genebank_id):
        """
        Returns all information for the given genebank that the user has access
        to, returning `None` if the user doesn't have genebank access.
        """
        if genebank_id not in self.accessible_genebanks:
            return None

        try:
            genebank = Genebank.get(genebank_id)
        except DoesNotExist:
            return None

        # No limit to viewing herds at this point. If you can view the genebank
        # you can view all the herds.
        herds = genebank.get_herds(user=self)
        genebank = genebank.as_dict()
        genebank["herds"] = herds
        return genebank

    def _can_edit_herd(self, herd):
        """
        Owner or genebank-manager rights on `herd` (admins are handled by the
        caller). On `GX1`/`MX1` — and so on every rabbit
        sold out of the genebank — only managers of its genebank, whatever
        owner privileges exist there.
        """
        if self.is_manager and herd.genebank_id in self.is_manager:
            return True
        if herd.herd in OUTSIDE_GENEBANK_HERDS:
            return False
        return bool(self.is_owner and herd.herd in self.is_owner)

    def can_edit(self, identifier):
        """
        Returns `true` if the user is allowed to edit the database item
        identified by `identifier`. `identifier` can be an `Individual.id` as int, `Individual.number`,
        a `Herd.herd` or a `Genebank.name`.

        `identifier` will be parsed as:

        `^([a-zA-Z][0-9]+-[0-9]+)$`: individual
        `^(([GM]X1)|[a-zA-Z][0-9]+)$`: herd
        and genebank otherwise.
        """
        # admins can edit anything
        if self.is_admin:
            return True

        if isinstance(identifier, int):
            try:
                with DATABASE.atomic():
                    individual = Individual.get(Individual.id == identifier)
                    if self._can_edit_herd(individual.current_herd):
                        return True
            except DoesNotExist:
                pass

        elif re.match("^([a-zA-Z][0-9]+-[0-9]+)$", identifier):
            try:
                with DATABASE.atomic():
                    individual = Individual.get(Individual.number == identifier)
                    if self._can_edit_herd(individual.current_herd):
                        return True
            except DoesNotExist:
                pass

        elif re.match("^(([GM]X1)|[a-zA-Z][0-9]+)$", identifier):
            try:
                with DATABASE.atomic():
                    herd = Herd.get(Herd.herd == identifier)
                    if self._can_edit_herd(herd):
                        return True
            except DoesNotExist:
                pass
        else:
            try:
                with DATABASE.atomic():
                    genebank = Genebank.get(Genebank.name == identifier)
                    if self.is_manager and genebank.id in self.is_manager:
                        return True
            except DoesNotExist:
                pass

        return False

    def owns_herd_of(self, herd):
        """Access to `herd` as one rabbit's own herd: by id (a herd code is unique only within its genebank), and
        never GX1/MX1, which hold every rabbit sold or imported from outside the genebank."""
        return herd is not None and herd.herd not in OUTSIDE_GENEBANK_HERDS and herd.id in self.effective_herd_ids()

    def can_issue_certificate(self, individual):
        """Check if user can issue/update certificates for this individual.

        The person who issues attests in her own name that the data match the rabbit, so only those with access to
        the origin herd (breeder) may: owner, main member, family or caretaker. Not the genebank manager or admin,
        who have not seen the rabbit (Jonas 2026-11-23, #141). Uses origin_herd, not current_herd: the breeder keeps
        the right after the rabbit moves to a new herd.
        """
        return self.owns_herd_of(individual.origin_herd)

    def can_view_certificate(self, individual):
        """Who may download or preview the certificate (ADR-0016): the
        current owner, the breeder (origin herd), the genebank's manager
        and admin. A viewer role on the genebank is not enough."""
        if self.is_admin or (self.is_manager and individual.origin_herd.genebank_id in self.is_manager):
            return True
        return self.owns_herd_of(individual.origin_herd) or self.owns_herd_of(individual.current_herd)

    class Meta:  # pylint: disable=too-few-public-methods
        """
        The Meta class is read automatically for Model information, and is used
        here to set the table name, as 'User' is a clearer system user name than
        the table name 'hbuser.
        """

        table_name = "hbuser"


class UserMessage(BaseModel):
    """
    Table storing messages to be displayed to users.
    """

    id = AutoField(primary_key=True, column_name="user_message_id")
    sender = ForeignKeyField(User, null=True)
    receiver = ForeignKeyField(User, null=False)
    level = CharField(12)
    message = TextField()
    send_time = DateTimeField()
    recieve_time = DateTimeField()


class YearlyReportRound(BaseModel):
    """
    Stores yearly report rounds. Managers or admins can create yearly rounds,
    and activate them based on start and end dates or manually.
    """

    id = AutoField(primary_key=True, column_name="yearly_report_round_id")
    report_year = IntegerField(unique=True)
    start_date = DateField(null=True)
    deadline = DateField(null=True)  # the support condition's last day; legacy rounds keep NULL
    end_date = DateField(null=True)
    manually_activated = BooleanField(default=False)
    is_active = BooleanField(default=False)
    created_by = ForeignKeyField(User)
    creation_date = DateTimeField(default=datetime.now)


class YearlyHerdReport(BaseModel):
    """
    Stores yearly reports for herds.

    The data field stores the report data in json format, but we refrained from
    storing it in a JSONField so that we could still use sqlite for testing.

    v2 (migration 51) writes status submitted or voided and leaves name, publish* and generated_by NULL; the legacy
    rows are status legacy. The CHECKs, the access-code FKs and the one-submitted index come from
    _create_arsrapport_schema.
    """

    id = AutoField(primary_key=True, column_name="yearly_herd_report_id")
    herd = ForeignKeyField(Herd)
    report_date = DateField()
    generated_by = ForeignKeyField(User, null=True)
    name = CharField(null=True)
    data = TextField()
    publish = BooleanField(null=True)
    publish_tel = BooleanField(null=True)
    publish_email = BooleanField(null=True)
    publish_address = BooleanField(null=True)
    version = CharField(null=True)
    round = ForeignKeyField(YearlyReportRound, null=True)
    status = TextField(default="legacy", constraints=[SQL("DEFAULT 'legacy'")])  # REPORT_STATUSES
    source = TextField(null=True)  # REPORT_SOURCES
    access_code_id = IntegerField(null=True)
    entered_by = ForeignKeyField(User, null=True, backref="+")
    on_time_set_by = ForeignKeyField(User, null=True, backref="+")
    support_approved_by = ForeignKeyField(User, null=True, backref="+")
    voided_by_user = ForeignKeyField(User, null=True, backref="+")
    inbox_item_id = IntegerField(null=True)  # no FK: the demo sync leaves out the queue's data
    received_at = TimestampTZField(null=True)
    support_approved_at = TimestampTZField(null=True)
    voided_at = TimestampTZField(null=True)
    on_time_override = BooleanField(null=True)
    revision = IntegerField(default=0, constraints=[SQL("DEFAULT 0")])
    voided_by_access_code_id = IntegerField(null=True)
    void_reason = TextField(null=True)


BUYER_CONTACT_YEARS = 5
MEMBERSHIP_OPTIN_FOR = timedelta(days=365)  # at most 12 months from the sale


BUYER_EMAIL_PHONE_CHECK = (
    "CONSTRAINT buyer_contact_email_phone_need_consent CHECK ((email IS NULL AND phone IS NULL) "
    "OR contact_consent_at IS NOT NULL OR membership_optin_at IS NOT NULL OR (email_notice_only AND phone IS NULL))"
)
BUYER_NOTICE_ONLY_CHECK = (
    "CONSTRAINT buyer_contact_notice_only_no_consent CHECK (NOT email_notice_only "
    "OR (phone IS NULL AND contact_consent_at IS NULL AND membership_optin_at IS NULL))"
)


class BuyerContact(BaseModel):
    """
    A buyer outside the association, on a sale to GX1/MX1 (ADR-0016): name, town and postal address on legitimate
    interest, e-mail and phone only with the buyer's yes, or the e-mail alone for the notice when the sale had no
    försäljningsbevis (#273). Not in AUDITED_TABLES, so erased values never stay in audit_log.
    """

    id = AutoField()
    name = TextField()
    town = TextField()
    postal_address = TextField(null=True)
    email = TextField(null=True)
    email_review_pending = BooleanField(default=False, constraints=[SQL("DEFAULT false")])
    # The transition for sales without a försäljningsbevis (2026–2027, #273): the seller gave the e-mail, which is
    # kept only until kopare.information has gone, and never with a phone or a yes.
    email_notice_only = BooleanField(default=False, constraints=[SQL("DEFAULT false")])
    erased_email_hash = TextField(null=True)  # lets the erase link find this contact after its e-mail is purged
    phone = TextField(null=True)
    contact_consent_at = TimestampTZField(null=True)  # may keep e-mail and phone while the buyer has it
    membership_optin_at = TimestampTZField(null=True)  # may be contacted about membership
    created_at = TimestampTZField(constraints=[SQL("DEFAULT now()")])
    created_by_user = ForeignKeyField(User, column_name="created_by_user_id", backref="+")
    # Five years from the sale's date (purge_at_for), set by the writer and again when a correction moves the sale.
    purge_at = TimestampTZField()

    @staticmethod
    def purge_at_for(sale_date):
        """Midnight in Stockholm five years after `sale_date` (a 29 February sale goes on 28 February)."""
        day = coerce_date(sale_date)
        try:
            day = day.replace(year=day.year + BUYER_CONTACT_YEARS)
        except ValueError:
            day = day.replace(year=day.year + BUYER_CONTACT_YEARS, day=28)
        return datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("Europe/Stockholm"))

    class Meta:  # pylint: disable=too-few-public-methods
        table_name = "buyer_contact"
        constraints = [SQL(BUYER_EMAIL_PHONE_CHECK), SQL(BUYER_NOTICE_ONLY_CHECK)]


HT_KINDS = ("BIRTH", "TRANSFER", "ATTESTATION", "CORRECTION")


class HerdTracking(BaseModel):
    """
    Event log of an individual's herd membership. Rows are never
    deleted (DB trigger) and never edited in place except by the void service.
    """

    id = AutoField(primary_key=True, column_name="herd_tracking_id")
    from_herd = ForeignKeyField(Herd, null=True, default=None)
    herd = ForeignKeyField(Herd, null=True, default=None)
    signature = ForeignKeyField(User, null=True, default=None)
    individual = ForeignKeyField(Individual)
    herd_tracking_date = DateField()
    # 999.5 — kind has NO model default: every writer states it.
    kind = CharField(max_length=20)
    operation_id = UUIDField()
    created_at = TimestampTZField(default=lambda: datetime.now(timezone.utc))
    notes = TextField(null=True)
    voided_at = TimestampTZField(null=True)
    voided_by_user = ForeignKeyField(User, null=True, column_name="voided_by_user_id", backref="voided_ht_rows")
    voided_reason = TextField(null=True)
    voided_operation_id = UUIDField(null=True)
    # Set when an undo clears this row's void, so undoing that undo can re-void it.
    restored_operation_id = UUIDField(null=True)
    restored_at = TimestampTZField(null=True)
    # Reserved links (NULL until the owning phase ships).
    yearly_herd_report = ForeignKeyField(YearlyHerdReport, null=True)  # Phase 6
    transfer_id = IntegerField(null=True)  # Phase 10 adds FK -> transfer
    # The buyer outside the association; erasing the contact nulls the link, the sale stays.
    holder_contact = ForeignKeyField(
        BuyerContact, null=True, on_delete="SET NULL", column_name="holder_contact_id", backref="+"
    )
    # The sale's buyer was removed (erasure, purge, void): never asked for or registered again. No personal data.
    buyer_removed = BooleanField(default=False, constraints=[SQL("DEFAULT false")])
    # The yearly report link as actor and voider; FKs to report_access_code from _create_arsrapport_schema.
    access_code_id = IntegerField(null=True)
    voided_by_access_code_id = IntegerField(null=True)

    class Meta:  # pylint: disable=too-few-public-methods
        """
        The Meta class is read automatically for Model information, and is used
        here to set the table name, as the table name is in snake case, which
        didn't fit the camel case class names.
        """

        table_name = "herd_tracking"

    def save(self, *args, **kwargs):
        """Append-only: inserts only. Void/unvoid go through utils.herd_tracking."""
        if self.id is not None and not kwargs.get("force_insert"):
            raise RuntimeError("herd_tracking rows are append-only — void and write a new row via utils.herd_tracking")
        return super().save(*args, **kwargs)


def ht_not_voided(model=None):
    """Peewee filter: herd-tracking rows that are not voided."""
    return (model or HerdTracking).voided_at.is_null(True)


def lock_breedings(ids):
    """
    Lock Breeding rows FOR NO KEY UPDATE in ascending id order. Still conflicts with the
    FOR UPDATE that update_breeding/delete_breeding take, but not with the FOR KEY SHARE a
    kit insert takes through its FK. SQLite has no row locks: no-op lock.
    """
    wanted = sorted({int(i) for i in ids})
    if not wanted:
        return []
    query = Breeding.select(Breeding.id).where(Breeding.id.in_(wanted)).order_by(Breeding.id)
    if not isinstance(DATABASE, SqliteDatabase):
        query = query.for_update("FOR NO KEY UPDATE")
    return list(query)


def lock_individuals(ids):
    """
    Lock individual rows FOR NO KEY UPDATE in ascending id order. Call first in every herd-tracking transaction.
    Re-locking a row the transaction already holds is free. SQLite has no row locks: no-op lock.

    Global lock order: Breeding rows (ascending) BEFORE Individual rows (ascending,
    all in ONE call). An edit that may write a Breeding locks it first.
    """
    wanted = sorted({int(i) for i in ids})
    if not wanted:
        return []
    query = Individual.select(Individual.id).where(Individual.id.in_(wanted)).order_by(Individual.id)
    if not isinstance(DATABASE, SqliteDatabase):
        query = query.for_update("FOR NO KEY UPDATE")
    return list(query)


LIFE_SIGN_KINDS = ("BIRTH", "TRANSFER", "ATTESTATION")  # CORRECTION is not a life sign
HOLDER_CHANGING_KINDS = ("BIRTH", "TRANSFER", "CORRECTION")
OUTSIDE_GENEBANK_HERDS = ("GX1", "MX1")  # "sold outside the genebank", one per genebank
ACTIVE_WINDOW_DAYS = 365 + 30


def coerce_date(value):
    """date | datetime | 'YYYY-MM-DD…' -> date (Peewee hands back whatever was assigned until a reload)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Not a date: {value!r}")


def validate_date(date_string):
    """
    Validates a date string and returns a datetime object or raises ValueError.
    """
    if not date_string:
        raise ValueError("Date missing")
    try:
        return datetime.strptime(date_string, "%Y-%m-%d")  # Try the first format
    except ValueError:
        try:
            return datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S.%fZ")  # Try the second format
        except ValueError as date_except:
            raise ValueError("Date must be formatted as yyyy-mm-dd or yyyy-mm-ddThh:mm:ss.sssZ.") from date_except


def ht_order_desc(model=None):
    """
    THE herd-tracking order: newest first; within a date
    BIRTH is always the day's first event (so it sorts last here), then write order.
    """
    m = model or HerdTracking
    return [m.herd_tracking_date.desc(), (m.kind == "BIRTH").asc(), m.id.desc()]


def ht_sort_key(row):
    """Chronological key — the exact reverse of ht_order_desc()."""
    return (coerce_date(row.herd_tracking_date), 0 if row.kind == "BIRTH" else 1, row.id)


def current_holder_row(individual_id, as_of=None):
    """The latest active row (any kind) — the holder; with `as_of`, the latest active row dated <= as_of."""
    query = HerdTracking.select().where(HerdTracking.individual == individual_id, ht_not_voided())
    if as_of is not None:
        query = query.where(HerdTracking.herd_tracking_date <= as_of)
    return query.order_by(*ht_order_desc()).first()


def latest_life_sign_date(individual_id):
    """Date of the latest active BIRTH/TRANSFER/ATTESTATION row, or None."""
    return (
        HerdTracking.select(fn.MAX(HerdTracking.herd_tracking_date))
        .where(
            HerdTracking.individual == individual_id,
            ht_not_voided(),
            HerdTracking.kind.in_(LIFE_SIGN_KINDS),
        )
        .scalar()
    )


def latest_ht_per_individual(as_of=None, distinct_on=False):
    """
    One row per individual: its holder row (`herd`, `ht_date`) plus `life_sign_date`.
    Ranked form (default): filter `rank == 1` after joining the aliased subquery.
    `distinct_on=True`: PostgreSQL DISTINCT ON form for the paginated explorer.
    """
    life_sign = (
        fn.MAX(HerdTracking.herd_tracking_date)
        .filter(HerdTracking.kind.in_(LIFE_SIGN_KINDS))
        .over(partition_by=[HerdTracking.individual])
    )
    query = HerdTracking.select(
        HerdTracking.individual.alias("i_id"),
        HerdTracking.herd.alias("herd"),
        HerdTracking.herd_tracking_date.alias("ht_date"),
        life_sign.alias("life_sign_date"),
    ).where(ht_not_voided())
    if as_of is not None:
        query = query.where(HerdTracking.herd_tracking_date <= as_of)
    if distinct_on:
        return query.order_by(HerdTracking.individual, *ht_order_desc()).distinct(HerdTracking.individual)
    rank = fn.ROW_NUMBER().over(partition_by=[HerdTracking.individual], order_by=ht_order_desc())
    return query.select_extend(rank.alias("rank"))


class Authenticators(BaseModel):
    """
    Authentication information for a user.
    """

    id = AutoField(primary_key=True, column_name="auth_id")
    user = ForeignKeyField(User)
    auth = CharField(9)
    auth_data = TextField(null=True)


# A Google identity is its "sub", stored as is. Two accounts linking one at once each lock only their own row.
GOOGLE_IDENTITY_INDEX_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS "idx_authenticators_google" ON "authenticators" (auth_data) '
    "WHERE auth = 'google'"
)


class SchemaHistory(BaseModel):
    """
    Contains schema migration history for the database.
    """

    version = IntegerField(primary_key=True)
    comment = TextField()
    applied = DateTimeField(null=True)


class GeneticMetricsHistory(BaseModel):
    """One row per closed report year, fully derived; replaced on reconcile.

    ``effective_population_size`` is the realised Ne over the year's members, the
    estimator the dashboard card uses for today (genetics.calculate_realised_ne),
    with its standard error ``ne_se`` and the animals behind it ``ne_n``.
    """

    id = AutoField(primary_key=True)
    genebank = ForeignKeyField(Genebank, backref="metrics_history")
    report_year = IntegerField()
    snapshot_date = DateField()  # = as_of; kept for the trends response
    as_of = DateField()
    definition_version = IntegerField()
    pedigree_version = BigIntegerField()
    population_size = IntegerField()
    active_count = IntegerField()
    mean_inbreeding = FloatField(null=True)
    mean_kinship = FloatField(null=True)
    founder_equivalents = FloatField(null=True)
    fge = FloatField(null=True)
    effective_population_size = FloatField(null=True)
    ne_se = FloatField(null=True)
    ne_n = IntegerField(null=True)
    data_quality = CharField(max_length=10)  # "high", "medium", "low"
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        indexes = ((("genebank", "report_year"), True),)


class GeneticsHistoryState(BaseModel):
    """Watermark of the last reconcile per genebank (also when nothing changed)."""

    genebank = ForeignKeyField(Genebank, primary_key=True, backref="history_state")
    checked_at = TimestampTZField()
    version = BigIntegerField()
    definition_version = IntegerField()
    algorithm_version = IntegerField(default=0)  # genetics_service.ALGORITHM_VERSION; 0 = before versioning

    class Meta:
        table_name = "genetics_history_state"


class DigitalCertificateV2(BaseModel):
    """Metadata for v2 certificates (WeasyPrint + pyHanko pipeline)."""

    id = AutoField()
    individual = ForeignKeyField(Individual, backref="certificates_v2")
    verification_token = UUIDField(unique=True, default=uuid.uuid4)
    certificate_type = CharField(default="pedigree")
    issued_by = ForeignKeyField(User)
    # The role she issued in (stamboken #6): "breeder", "admin" or "manager". NULL on rows issued before it existed.
    issued_as = CharField(max_length=20, null=True)
    issued_at = DateTimeField(default=datetime.now)
    file_path = CharField()
    checksum = CharField(64)
    is_current = BooleanField(default=True)

    class Meta:
        table_name = "digitalcertificatev2"

    @classmethod
    def retire_current(cls, individual):
        """The only place is_current is turned off: the individual no longer has a current digital certificate."""
        cls.update(is_current=False).where(cls.individual == individual, cls.is_current).execute()

    @classmethod
    def issue_current(cls, individual, **fields):
        """The only place a current row is created: the previous one is retired first (one current per individual)."""
        cls.retire_current(individual)
        return cls.create(individual=individual, is_current=True, **fields)


# At most one current certificate per individual — a concurrent re-issue race
# gets an IntegrityError instead of two is_current rows (Postgres partial
# unique index, created by create_tables in migrate_20_to_21).
DigitalCertificateV2.add_index(
    DigitalCertificateV2.index(
        DigitalCertificateV2.individual,
        name="digitalcertificatev2_one_current",
        unique=True,
        where=DigitalCertificateV2.is_current,
    )
)


class AuditLog(BaseModel):
    """
    Generic audit log table. Populated by PostgreSQL triggers on tracked tables.
    Stores old/new row data as JSONB for every INSERT, UPDATE, DELETE.
    """

    id = BigAutoField(primary_key=True)
    schema_name = TextField(default="public")
    table_name = TextField()
    record_id = TextField()
    operation = TextField()  # INSERT / UPDATE / DELETE
    old_data = BinaryJSONField(null=True)
    new_data = BinaryJSONField(null=True)
    changed_fields = ArrayField(TextField, null=True)  # PG text[]
    changed_by = TextField(null=True)
    ip_address = TextField(null=True)
    changed_at = DateTimeField(constraints=[SQL("DEFAULT now()")])
    transaction_id = BigIntegerField(null=True)

    class Meta:
        table_name = "audit_log"
        indexes = (
            (("table_name", "record_id"), False),
            (("changed_at",), False),
            (("changed_by",), False),
        )


class Member(BaseModel):
    """
    Person row under a Membership (Member Model v2). Linked to User via
    `user` FK when auto-linking matches an existing account. Membership-
    level facts (number, status, address, consent) live on Membership.
    """

    id = AutoField(primary_key=True, column_name="member_id")
    first_name = CharField(max_length=100, null=False)
    last_name = CharField(max_length=100, null=False)
    # `email` is the CONTACT email — what /ansok collected or what the
    # matrikel CSV had. It is never used for OAuth matching.
    email = CharField(max_length=255, null=True)
    phone = CharField(max_length=50, null=True)
    user = ForeignKeyField(User, null=True, backref="member_records")
    # `workspace_email` is the PROVISIONED login email
    # (firstname.lastname@gotlandskaninen.se), set by Phase 9 after
    # Workspace account provisioning. The auto-link helper matches
    # User.email == Member.workspace_email — never against contact email.
    workspace_email = CharField(max_length=255, null=True)
    # When `email` starts to count for login (utils.matrikel.set_member_email); NULL: at once.
    email_login_from = TimestampTZField(null=True)
    membership = ForeignKeyField(Membership, null=False, backref="persons")
    role = CharField(max_length=20, default="huvudmedlem")
    end_date = DateField(null=True)
    gdpr_consented_at = DateTimeField(null=True)
    notes = TextField(null=True)
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "member"

    @property
    def display_name(self) -> str:
        name = f"{self.first_name.strip()} {self.last_name.strip()}".strip()
        if not name and self.role == "huvudmedlem":
            return self.membership.organization_name or ""
        return name

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)


class MemberApplication(BaseModel):
    """
    Pending application for membership, submitted via public /ansok form.
    Approve → creates Member; reject → stores reason without Member creation.
    """

    id = AutoField(primary_key=True, column_name="member_application_id")
    first_name = CharField(max_length=100, null=False)
    last_name = CharField(max_length=100, null=False)
    email = CharField(max_length=255, null=False)
    phone = CharField(max_length=50, null=True)
    address = TextField(null=True)
    # Phase 19: structured address collected by /ansok (no backfill —
    # historic applications keep their free-text street line).
    postal_code = CharField(max_length=10, null=True)
    city = CharField(max_length=100, null=True)
    # Optional billing address from the form; approval copies it to the
    # membership. Same columns and meaning as on Membership.
    billing_name = CharField(max_length=200, null=True)
    billing_address = TextField(null=True)
    billing_postal_code = CharField(max_length=10, null=True)
    billing_city = CharField(max_length=100, null=True)
    billing_email = CharField(max_length=255, null=True)
    billing_reference = CharField(max_length=100, null=True)
    motivation = TextField(null=True)
    gdpr_consented_at = DateTimeField(null=False)
    status = CharField(max_length=20, default="pending")
    reviewed_by = ForeignKeyField(User, null=True, backref="reviewed_applications")
    reviewed_at = DateTimeField(null=True)
    rejection_reason = TextField(null=True)
    created_member = ForeignKeyField(Member, null=True, backref="source_application")
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "member_application"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)


class HerdAccessGrant(BaseModel):
    """
    Person-to-herd edit permission with optional expiry (Member Model v2).

    Active iff revoked_at IS NULL AND (valid_until IS NULL OR
    valid_until >= today) AND the person row is active (end_date IS NULL).
    One row per (member, herd) pair for its whole lifecycle — re-grants
    clear revoked_at on the same row.
    """

    id = AutoField(primary_key=True, column_name="herd_access_grant_id")
    member = ForeignKeyField(Member, null=False, backref="grants")
    herd = ForeignKeyField(Herd, null=False, backref="access_grants")
    valid_until = DateField(null=True)
    revoked_at = DateTimeField(null=True)
    granted_by = ForeignKeyField(User, null=False, backref="granted_herd_access")
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "herd_access_grant"
        indexes = ((("member", "herd"), True),)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)


class MatrikelAudit(BaseModel):
    """
    Append-only audit log for matrikel mutations (Member Model v2).
    Payloads are subject to GDPR redaction (utils/matrikel.py).
    """

    id = AutoField(primary_key=True, column_name="matrikel_audit_id")
    actor = ForeignKeyField(User, null=True, backref="matrikel_actions")  # NULL: the nightly anonymization (#70)
    action = CharField(max_length=50, null=False)
    membership = ForeignKeyField(Membership, null=False, backref="audit_entries")
    payload = BinaryJSONField(default=dict)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "matrikel_audit"


class IndividualCommand(BaseModel):
    """One write command on an individual (ADR-0017). Append-only: an undo is a row that names the one it undoes."""

    id = BigAutoField(primary_key=True)
    operation_id = UUIDField(unique=True)
    request_id = UUIDField(index=True)  # one per execute(); the commands of a legacy PATCH share it
    command = CharField(40)  # the command class name, or "Undo"
    individual = ForeignKeyField(Individual)
    actor = ForeignKeyField(User, null=True)  # pseudonymised with the user, never SET NULL
    # Or the yearly report link: exactly one of the two (individual_command_actor_check, _create_arsrapport_schema).
    access_code_id = IntegerField(null=True)
    created_at = TimestampTZField(default=lambda: datetime.now(timezone.utc))
    before = BinaryJSONField(null=True)
    after = BinaryJSONField(null=True)
    undoes = UUIDField(null=True, index=True)  # not unique: an attestation restored in herd-tracking is undone again
    reason = TextField(null=True)
    redacted_at = TimestampTZField(null=True)

    class Meta:
        table_name = "individual_command"
        indexes = ((("individual", "created_at"), False),)


def _utcnow():
    return datetime.now(timezone.utc)


class MailMessage(BaseModel):
    """One outgoing mail (docs/mejl.md): template, ids and a recipient reference, never an address or a text."""

    id = AutoField()
    kind = TextField()
    params = BinaryJSONField(default=dict, index=False)  # ids and flags only, never searched
    recipient_kind = TextField()
    recipient_id = IntegerField()
    ref_type = TextField(null=True)
    ref_id = IntegerField(null=True)
    # SET NULL: a queued mail must never make a write fail.
    herd = ForeignKeyField(Herd, null=True, on_delete="SET NULL")
    genebank = ForeignKeyField(Genebank, null=True, on_delete="SET NULL")
    priority = SmallIntegerField()
    category = CharField(1)  # T transaction, N notice
    dedupe_key = TextField(null=True, unique=True)
    status = TextField(default="queued")
    attempts = SmallIntegerField(default=0)
    next_attempt_at = TimestampTZField(default=_utcnow)
    claimed_at = TimestampTZField(null=True)
    claim_token = UUIDField(null=True)
    sent_at = TimestampTZField(null=True)
    address_hash = TextField(null=True)
    last_error = TextField(null=True)
    created_at = TimestampTZField(default=_utcnow)
    created_by = ForeignKeyField(User, null=True, on_delete="SET NULL", column_name="created_by")

    class Meta:
        table_name = "mail_message"
        indexes = (
            (("status", "next_attempt_at", "priority", "id"), False),
            (("ref_type", "ref_id"), False),
            (("recipient_kind", "recipient_id"), False),
        )


class BuyerInvitation(BaseModel):
    """A delivered invitation, without a link to the buyer or the sale. Follows the mail history's retention."""

    email_hash = TextField(primary_key=True)
    created_at = TimestampTZField()

    class Meta:
        table_name = "mail_buyer_invitation"


class MailAttempt(BaseModel):
    """One SMTP attempt or bounce of a mail."""

    id = AutoField()
    message = ForeignKeyField(MailMessage, on_delete="CASCADE")
    at = TimestampTZField(default=_utcnow)
    source = TextField()  # smtp, bounce
    result = TextField()  # sent, temporary, permanent, systemic, bounce
    smtp_code = TextField(null=True)
    detail = TextField(null=True)  # scrubbed of addresses

    class Meta:
        table_name = "mail_attempt"


class MailSender(BaseModel):
    """The mail sender's one row: its heartbeat, for the "queue stalled" alarm, and its pause after a systemic error."""

    id = IntegerField(primary_key=True, default=1, constraints=[Check("id = 1")])
    last_run_at = TimestampTZField(null=True)
    paused_until = TimestampTZField(null=True)
    code_limit_at = TimestampTZField(null=True)
    code_queue_errors = ArrayField(TimestampTZField, null=True, index=False)  # three most recent failures

    class Meta:
        table_name = "mail_sender"


class LoginCode(BaseModel):
    """One one-time code by mail (utils.login_code). It holds a nonce, never the code, which is computed from it."""

    id = AutoField()
    member = ForeignKeyField(Member, on_delete="CASCADE")
    user = ForeignKeyField(User, null=True, on_delete="CASCADE")  # the person's account when the code was made
    purpose = TextField(constraints=[Check("purpose IN ('login', 'ny_adress')")])
    address_hash = TextField()  # where the code went
    new_address = TextField(null=True)  # ny_adress only, until the code is used or has expired
    nonce = TextField()
    browser_hash = TextField()
    created_at = TimestampTZField(default=_utcnow)
    failed = SmallIntegerField(default=0)
    used_at = TimestampTZField(null=True)  # used, or voided by an address change

    class Meta:
        table_name = "login_code"
        indexes = ((("browser_hash",), False), (("created_at",), False))


class MemberPreviousAddress(BaseModel):
    """An address a person had (utils.matrikel.set_member_email), and how long it still counts for login."""

    id = AutoField()
    member = ForeignKeyField(Member, on_delete="CASCADE")
    address = TextField()
    login_until = TimestampTZField(null=True)  # NULL: not a login address at all
    purge_at = TimestampTZField()
    changed_by = ForeignKeyField(User, null=True, on_delete="SET NULL", column_name="changed_by")

    class Meta:
        table_name = "member_previous_address"
        indexes = ((("purge_at",), False),)


# The intake queue (docs/inkorg.md). None of these tables is audited: inbox_event is the history, and audit
# copies would keep personal data after the purge.


class InboxItem(BaseModel):
    """What came in at one go (an upload or a mail), with its state and its handler."""

    id = AutoField()
    kind = TextField()  # upload, mail, meddelande, kontroll, avisering
    state = TextField(default="ny")
    genebank = ForeignKeyField(Genebank, null=True, on_delete="SET NULL")
    herd = ForeignKeyField(Herd, null=True, on_delete="SET NULL")
    member = ForeignKeyField(Member, null=True, on_delete="SET NULL")  # the matched sender of a mail
    sender_user = ForeignKeyField(User, null=True, on_delete="SET NULL", backref="+")  # the uploader
    sender_address = TextField(null=True)  # mail only
    # Gmail authenticated the From address's domain (SPF or DKIM); None for an upload. Mail goes back only then.
    sender_authenticated = BooleanField(null=True)
    message = TextField(null=True)
    gmail_message_id = TextField(null=True, unique=True)
    received_at = TimestampTZField(default=_utcnow)
    assigned_to = ForeignKeyField(User, null=True, on_delete="SET NULL", backref="+", column_name="assigned_to")
    assigned_at = TimestampTZField(null=True)
    state_changed_at = TimestampTZField(default=_utcnow)
    closed_at = TimestampTZField(null=True)
    duplicate_of = ForeignKeyField("self", null=True, on_delete="SET NULL", backref="+", column_name="duplicate_of")
    stalled = BooleanField(default=False)
    missing_proof = BooleanField(default=False)
    ref_type = TextField(null=True)  # kontroll and avisering point at another feature's row
    ref_id = IntegerField(null=True)
    # Structured fields with no personal data: a purchase notice's, or a bought rabbit's sent photos' (an upload, S7),
    # number, seller and date, and the sent photos' receipt for a retry; on a report photo held for a purchase, its
    # purpose (inbox.PURPOSE).
    ref_data = BinaryJSONField(null=True, index=False)

    class Meta:
        table_name = "inbox_item"
        indexes = ((("state", "received_at"), False),)


def _initial_interpretation():
    """A new document waits for the image reading when it is on, however it came in (docs/inkorg.md, "Tolkning")."""
    from utils.inbox_interpreter import initial_status  # pylint: disable=import-outside-toplevel  # it imports us

    return initial_status()


class InboxDocument(BaseModel):
    """One image of an item (a photo, or a page of a PDF), under PRIVATE_UPLOAD_FOLDER."""

    id = AutoField()
    item = ForeignKeyField(InboxItem, on_delete="CASCADE", backref="documents")
    original_path = TextField(null=True)  # NULL once the original is purged or erased (utils/inbox_purge.py)
    public_path = TextField(null=True)  # the masked copy shown on the rabbit
    mime = TextField()
    sha256 = CharField(64, index=True)
    quality = BinaryJSONField(null=True, index=False)
    doc_type = TextField(default="intyg")
    cert_format = TextField(null=True)
    rotation = SmallIntegerField(default=0)
    mask_rects = BinaryJSONField(null=True, index=False)
    interpretation_status = TextField(default=_initial_interpretation)  # av, vantar, klar or misslyckad
    attempts = SmallIntegerField(default=0)
    interpreter = TextField(null=True)
    interpretation = BinaryJSONField(null=True, index=False)
    proposal = BinaryJSONField(null=True, index=False)
    interpreted_at = TimestampTZField(null=True)
    waiting_for = BinaryJSONField(null=True)  # the parents' numbers; GIN, searched with @> on every registration
    individual = ForeignKeyField(Individual, null=True, on_delete="SET NULL", backref="+")
    # The sale a proof (bevis) belongs to. No FK: herd_tracking rows are never deleted, and one would stop
    # TRUNCATE herd_tracking, as for its reserved link transfer_id (holder_contact_id is a real FK, to buyer_contact).
    herd_tracking_id = IntegerField(null=True)
    purge_after = TimestampTZField(null=True)
    done_at = TimestampTZField(null=True)
    # The members the photo shows, recorded when it is saved through the queue, so an erasure finds it.
    seller_member = ForeignKeyField(Member, null=True, on_delete="SET NULL", backref="+")
    buyer_member = ForeignKeyField(Member, null=True, on_delete="SET NULL", backref="+")
    # The paper certificate number the document was saved as, and whether its handler found the certificate and the
    # registry in agreement when the copy was made (the rabbit's badge, only while the rabbit keeps that number).
    saved_certificate = TextField(null=True)
    saved_number = TextField(null=True)
    verified_at = TimestampTZField(null=True)
    verified_by = ForeignKeyField(User, null=True, on_delete="SET NULL", backref="+")

    class Meta:
        table_name = "inbox_document"


class InboxEvent(BaseModel):
    """An item's history: came in, taken, assigned, state, saved, opened."""

    id = BigAutoField()
    item = ForeignKeyField(InboxItem, on_delete="CASCADE", backref="events")
    at = TimestampTZField(default=_utcnow)
    user = ForeignKeyField(User, null=True, on_delete="SET NULL", backref="+")
    kind = TextField()
    detail = BinaryJSONField(null=True, index=False)

    class Meta:
        table_name = "inbox_event"
        indexes = ((("item", "at"), False),)


class InboxOperation(BaseModel):
    """The trace "inlagd från foto av": a write's operation id, its handler and document. Outlives both."""

    id = BigAutoField()
    operation_id = UUIDField(index=True)
    user = ForeignKeyField(User, null=True, on_delete="SET NULL", backref="+")
    document = ForeignKeyField(InboxDocument, null=True, on_delete="SET NULL", backref="+")
    created_at = TimestampTZField(default=_utcnow)

    class Meta:
        table_name = "inbox_operation"


class Notice(BaseModel):
    """A notice in Stamboken, mailed in the daily digest unless the user turned that off."""

    id = AutoField()
    user = ForeignKeyField(User, on_delete="CASCADE", backref="+")
    kind = TextField()
    item = ForeignKeyField(InboxItem, null=True, on_delete="CASCADE", backref="+")
    individual = ForeignKeyField(Individual, null=True, on_delete="CASCADE", backref="+")
    created_at = TimestampTZField(default=_utcnow)
    read_at = TimestampTZField(null=True)
    mailed_at = TimestampTZField(null=True)

    class Meta:
        indexes = ((("user", "read_at"), False),)


class NoticeSetting(BaseModel):
    user = ForeignKeyField(User, primary_key=True, on_delete="CASCADE", backref="+")
    mail_enabled = BooleanField(default=True)

    class Meta:
        table_name = "notice_setting"


class GmailSync(BaseModel):
    """The Gmail reader's one row (a later part of the queue)."""

    id = IntegerField(primary_key=True, default=1, constraints=[Check("id = 1")])
    history_id = TextField(null=True)
    last_run_at = TimestampTZField(null=True)
    last_error = TextField(null=True)

    class Meta:
        table_name = "gmail_sync"


class GmailProcessed(BaseModel):
    """One row per Gmail message handled, so a message read twice is handled once."""

    gmail_message_id = TextField(primary_key=True)
    kind = TextField()  # item, reply, bounce, ignored; retry (its content failed) and failed (FAILED_AFTER times)
    failures = SmallIntegerField(default=0)  # runs in a row in which the message's content could not be read
    item = ForeignKeyField(InboxItem, null=True, on_delete="SET NULL", backref="+")
    at = TimestampTZField(default=_utcnow)

    class Meta:
        table_name = "gmail_processed"


INBOX_MODELS = [
    InboxItem,
    InboxDocument,
    InboxEvent,
    InboxOperation,
    Notice,
    NoticeSetting,
    GmailSync,
    GmailProcessed,
]

# Yearly report v2 (migration 51). Not audited: buyers, contact values and free text must not stay in audit_log.

REPORT_STATUSES = ("submitted", "voided", "legacy")
REPORT_SOURCES = ("login", "link", "paper")
CONSENT_SOURCES = ("profil", "login", "link", "paper", "admin")


def _sql_in(column, values):
    """`column IN ('a', 'b')` for a CHECK."""
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class ReportAccessCode(BaseModel):
    """A herd's yearly report link for one round (step 3). Neither the code nor a hash of it is stored."""

    id = AutoField()
    herd = ForeignKeyField(Herd, backref="+")
    round = ForeignKeyField(YearlyReportRound, backref="+")
    member = ForeignKeyField(Member, backref="+")  # the main member who got the link
    created_at = TimestampTZField(default=_utcnow)
    expires_at = DateField()
    revoked_at = TimestampTZField(null=True)
    last_opened_at = TimestampTZField(null=True)

    class Meta:
        table_name = "report_access_code"


class YearlyReportRoundGenebank(BaseModel):
    """A genebank's activation of a round, and when its invitations go out."""

    id = AutoField()
    round = ForeignKeyField(YearlyReportRound, backref="+")
    genebank = ForeignKeyField(Genebank, backref="+")
    activated_by = ForeignKeyField(User, backref="+")
    activated_at = TimestampTZField()
    send_at = DateField()
    sent_at = TimestampTZField(null=True)

    class Meta:
        table_name = "yearly_report_round_genebank"
        indexes = ((("round", "genebank"), True),)


class YearlyReportSubmission(BaseModel):
    """One row per Skicka, never changed: what it sent, and the commands and measurements it wrote."""

    id = AutoField()
    report = ForeignKeyField(YearlyHerdReport, backref="+")
    submission_key = UUIDField(unique=True)
    created_at = TimestampTZField(default=_utcnow)
    source = TextField()
    user = ForeignKeyField(User, null=True, backref="+")
    access_code = ForeignKeyField(ReportAccessCode, null=True, backref="+")
    operation_ids = BinaryJSONField(default=list, index=False, constraints=[SQL("DEFAULT '[]'")])
    added_measurements = BinaryJSONField(default=list, index=False, constraints=[SQL("DEFAULT '[]'")])
    data = BinaryJSONField(index=False)
    request_hash = TextField()  # keyed HMAC of the parsed body, matrikel and buyers included (D21)

    class Meta:
        table_name = "yearly_report_submission"
        constraints = [
            SQL(f"CONSTRAINT yearly_report_submission_source_check CHECK ({_sql_in('source', REPORT_SOURCES)})"),
            SQL(
                "CONSTRAINT yearly_report_submission_actor_check CHECK ((user_id IS NULL) <> (access_code_id IS NULL))"
            ),
        ]


class SaleProposal(BaseModel):
    """A sale proposed by a caretaker or the report link (step 4), which a manager approves or rejects."""

    id = AutoField()
    report = ForeignKeyField(YearlyHerdReport, backref="+")
    submission = ForeignKeyField(YearlyReportSubmission, backref="+")
    individual = ForeignKeyField(Individual, backref="+")
    to_herd = ForeignKeyField(Herd, null=True, backref="+")
    buyer = BinaryJSONField(null=True, index=False)
    sale_date = DateField()
    buyer_notified_at = TimestampTZField(null=True)
    state = TextField(default="foreslagen", constraints=[SQL("DEFAULT 'foreslagen'")])
    decided_by = ForeignKeyField(User, null=True, backref="+")
    decided_at = TimestampTZField(null=True)
    reason = TextField(null=True)
    # No FKs, as inbox_document.herd_tracking_id: TRUNCATE herd_tracking and the demo sync keep working.
    herd_tracking_id = IntegerField(null=True)
    inbox_item_id = IntegerField(null=True)
    created_at = TimestampTZField(default=_utcnow)

    class Meta:
        table_name = "sale_proposal"
        constraints = [
            SQL(
                "CONSTRAINT sale_proposal_state_check "
                f"CHECK ({_sql_in('state', ('foreslagen', 'godkand', 'avvisad', 'atertagen'))})"
            )
        ]


class YearlyReportDraft(BaseModel):
    """The server draft of a herd's report: the body without the matrikel and the buyers."""

    id = AutoField()
    herd = ForeignKeyField(Herd, backref="+")
    round = ForeignKeyField(YearlyReportRound, backref="+")
    data = BinaryJSONField(index=False)
    submission_key = UUIDField(null=True)
    updated_at = TimestampTZField()
    updated_by_user = ForeignKeyField(User, null=True, backref="+")
    updated_by_access_code = ForeignKeyField(ReportAccessCode, null=True, backref="+")

    class Meta:
        table_name = "yearly_report_draft"
        indexes = ((("herd", "round"), True),)


class MemberChangeRequest(BaseModel):
    """A pending matrikel change from the report link (step 5), or a confirmed e-mail change from paper."""

    id = AutoField()
    member = ForeignKeyField(Member, backref="+")
    submission = ForeignKeyField(YearlyReportSubmission, backref="+")
    kind = TextField()
    value = BinaryJSONField(index=False)
    access_code = ForeignKeyField(ReportAccessCode, null=True, backref="+")
    created_at = TimestampTZField(default=_utcnow)
    expires_at = TimestampTZField(null=True)
    old_confirmed_at = TimestampTZField(null=True)
    confirmed_at = TimestampTZField(null=True)
    revoked_at = TimestampTZField(null=True)

    class Meta:
        table_name = "member_change_request"
        constraints = [
            SQL(
                "CONSTRAINT member_change_request_kind_check "
                f"CHECK ({_sql_in('kind', ('kontakt', 'epost', 'konto', 'publicering'))})"
            )
        ]


class PublicationConsentChange(BaseModel):
    """One row per actual change of a membership's publication consent, from every path that writes it."""

    id = AutoField()
    membership = ForeignKeyField(Membership, backref="+")
    at = TimestampTZField(default=_utcnow)
    value = BinaryJSONField(index=False)
    text_version = TextField()
    source = TextField()
    user = ForeignKeyField(User, null=True, on_delete="SET NULL", backref="+")
    report = ForeignKeyField(YearlyHerdReport, null=True, backref="+")
    submission_id = IntegerField(null=True)  # the report's submission that wrote it; no FK, as for the demo sync

    class Meta:
        table_name = "publication_consent_change"
        constraints = [
            SQL(f"CONSTRAINT publication_consent_change_source_check CHECK ({_sql_in('source', CONSENT_SOURCES)})")
        ]


ARSRAPPORT_MODELS = [
    ReportAccessCode,
    YearlyReportRoundGenebank,
    YearlyReportSubmission,
    SaleProposal,
    YearlyReportDraft,
    MemberChangeRequest,
    PublicationConsentChange,
]

MODELS = [
    Genebank,
    Membership,
    MemberNumberCounter,
    Herd,
    Color,
    Breeding,
    Individual,
    Bunny,
    IndividualFile,
    Disease,
    IndividualDisease,
    Weight,
    Bodyfat,
    AccountRulesSnapshot,
    User,
    UserMessage,
    YearlyReportRound,
    YearlyHerdReport,
    BuyerContact,
    HerdTracking,
    Authenticators,
    AuditLog,
    SchemaHistory,
    GeneticMetricsHistory,
    GeneticsHistoryState,
    Member,
    MemberApplication,
    DigitalCertificateV2,
    HerdAccessGrant,
    MatrikelAudit,
    IndividualCommand,
    MailMessage,
    BuyerInvitation,
    MailAttempt,
    MailSender,
    LoginCode,
    MemberPreviousAddress,
    *INBOX_MODELS,
    *ARSRAPPORT_MODELS,
]


def init():
    """
    Initializes all tables in the database, if they're not already available.

    We keep a special eye on the Breeding table, as i uses deferred foreign keys
    which need to be created once the individual table has been created.
    """

    # need to keep track of the breeding table
    logger.info("Initializing database")
    created_breeding = False
    # Only a database that has no schema history at all is a fresh bootstrap.
    # Sampled BEFORE the create loop below, which is what creates the table.
    fresh_bootstrap = not SchemaHistory.table_exists()
    for model in MODELS:
        if not model.table_exists():
            # AuditLog is created via raw SQL DDL (PG-specific types)
            if model == AuditLog:
                continue
            logger.info("Creating database table %s", model.__name__)
            if model.__name__ == "Breeding":
                created_breeding = True
            model.create_table()
    # sqlite can't add constraints after creation
    if created_breeding and not isinstance(DATABASE, SqliteDatabase):
        logger.info("Creating foreign keys for breeding table")
        # pylint: disable=protected-access
        Breeding._schema.create_foreign_key(Breeding.mother)
        Breeding._schema.create_foreign_key(Breeding.father)
    if not isinstance(DATABASE, SqliteDatabase):
        _add_herd_contact_member_fk()  # every init: an interrupted first one may have died before member existed

    _lock_account_rules_snapshots()

    # Stamp the bootstrap version — but ONLY on a database this call created
    # from nothing. Stamping an existing (possibly partially migrated) database
    # would make check_migrations() read MAX(version) == CURRENT_SCHEMA_VERSION
    # and skip the migrations it still owes.
    #
    # This used to be `SchemaHistory(version=..., comment=...).save()`, which
    # never wrote anything: `version` is a plain (non-AUTO) primary key, so
    # peewee turns save() on a populated instance into an UPDATE, and on a
    # fresh database that matched zero rows. on_conflict_ignore guards against
    # two processes bootstrapping the same empty database concurrently.
    if fresh_bootstrap:
        with DATABASE.atomic():
            SchemaHistory.insert(  # pylint: disable=E1120
                version=CURRENT_SCHEMA_VERSION,
                comment="Bootstrapped",
                applied=datetime.now(),
            ).on_conflict_ignore().execute()

    # Create audit table + triggers for fresh databases (migration won't run)
    _create_audit_table_and_triggers()
    # Phase 17: demo_sync_status is raw-SQL-managed — same
    # fresh-database bootstrap path as the audit table.
    _create_demo_sync_status_table()
    # Same reason: member partial-unique indexes are raw SQL — apply them on
    # fresh databases too (pytest stack bootstraps through init(), not
    # migrations). Idempotent (IF NOT EXISTS).
    _create_member_indexes()
    # v2 matrikel indexes/CHECKs and the member-number counter row follow
    # the same pattern (migrations never run on init()-bootstrapped DBs).
    _create_matrikel_indexes()
    _seed_member_number_counter()

    # Unique litter_number index for fresh databases (migration won't run)
    _create_breeding_litter_number_index()

    # Same for the unique Google identity (migrate_47_to_48)
    DATABASE.execute_sql(GOOGLE_IDENTITY_INDEX_SQL)

    # 999.5: herd_tracking CHECKs, partial indexes, created_at default (migration won't run)
    _create_herd_tracking_guards()

    # 999.8: global genetics version + deferred bump triggers (migration won't run)
    _create_genetics_version_guards()

    # ADR-0016: herd_tracking.holder_contact_id -> buyer_contact on a database whose herd_tracking predates it
    _create_buyer_contact_guards()

    # Yearly report v2: CHECKs, access-code FKs and the new void CHECK (migration won't run)
    _create_arsrapport_schema()

    # The support account's type and the emptied herd columns (migrate_57_to_58)
    _create_support_account_guards()


def verify(try_init=True):
    """
    Initialize the database, verify the tables in the database, and verify that
    we can select on each table.
    """
    check_migrations()

    all_ok = True
    for model in MODELS:
        # AuditLog is PostgreSQL-only (uses JSONB, triggers)
        if model == AuditLog and isinstance(DATABASE, SqliteDatabase):
            continue
        if model.table_exists():
            model(database=DATABASE).select().execute()
        else:
            all_ok = False
            break

    if not all_ok and try_init:
        logger.warning("Database has problems. Attempting re-initialization.")
        init()
        return verify(False)

    return all_ok


#
# Templates for database migrations.
#
# Migrations should be expected to run incrementally, each function supporting going
# from schema version N to N+1.
#
# In case data changes are necessary, they should be included in the migration.
#
# Migrations should also support replays, i.e. on a repeated call to a migration
# that has already been applied, it should simply do nothing rather than fail.
#


def migrate_none_to_1():
    """
    Migrate between no schema version and version 1.
    """

    logger.info("Migrating to schema version 1")

    with DATABASE.atomic():
        SchemaHistory.create_table()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=1, comment="Create schema history table"
        ).execute()


def migrate_1_to_2():
    """
    Migrate between schema version 1 and 2.
    """

    with DATABASE.atomic():
        cols = [x.name for x in DATABASE.get_columns("schemahistory")]

        if "applied" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("schemahistory", "applied", DateTimeField(null=True)))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=2,
            comment="Fix schema history table",
            applied=datetime.now(),
        ).execute()


def migrate_2_to_3():
    """
    Migrate between schema version 2 and 3.
    """

    with DATABASE.atomic():
        tables = DATABASE.get_tables()

        if "colour" in tables:
            migrate(DATABASE_MIGRATOR.rename_table("colour", "color"))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=3, comment="colour is now color", applied=datetime.now()
        ).execute()


def migrate_3_to_4():
    """
    Migrate between schema version 3 and 4.
    """

    with DATABASE.atomic():
        if "individual" not in DATABASE.get_tables() or "color" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=4,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()

            return

        cols = [x.name for x in DATABASE.get_columns("individual")]

        if "colour_note" in cols:
            migrate(DATABASE_MIGRATOR.rename_column("individual", "colour_note", "color_note"))
        if "colour_id" in cols:
            migrate(DATABASE_MIGRATOR.rename_column("individual", "colour_id", "color_id"))

        cols = [x.name for x in DATABASE.get_columns("color")]
        if "colour_id" in cols:
            migrate(DATABASE_MIGRATOR.rename_column("color", "colour_id", "color_id"))

        SchemaHistory.insert(  # pylint: disable=E1120
            version=4,
            comment="colour to color in fields",
            applied=datetime.now(),
        ).execute()


def migrate_4_to_5():
    """
    Migrate between schema version 4 and 5.
    """
    with DATABASE.atomic():
        if "individual" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=5,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("individual")]

        if "digital_certificate" not in cols:
            migrate(
                DATABASE_MIGRATOR.add_column(
                    "individual",
                    "digital_certificate",
                    IntegerField(null=True, unique=True),
                )
            )
        SchemaHistory.insert(  # pylint: disable=E1120
            version=5,
            comment="Set up digital certificate ids",
            applied=datetime.now(),
        ).execute()


def migrate_5_to_6():
    """
    Migrate between schema version 5 and 6.
    """

    with DATABASE.atomic():
        if "hbuser" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=6,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("hbuser")]

        if "password_hash" in cols:
            # Go through hbuser and fill in authenticators from the old data.
            pw_cursor = DATABASE.execute_sql("select user_id,password_hash from hbuser")

            for user_data in pw_cursor.fetchmany():
                auth = Authenticators(user=user_data[0], auth="password", auth_data=user_data[1])
                auth.save()
            migrate(DATABASE_MIGRATOR.drop_column("hbuser", "password_hash"))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=6,
            comment="Remove password_hash from hbuser",
            applied=datetime.now(),
        ).execute()


def migrate_6_to_7():
    """
    Migrate between schema version 6 and 7.
    """

    with DATABASE.atomic():
        if "hbuser" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=7,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("hbuser")]

        if "fullname" not in cols:
            # Go through hbuser and fill in authenticators from the old data.
            migrate(DATABASE_MIGRATOR.add_column("hbuser", "fullname", TextField(null=True)))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=7,
            comment="Add fullname to hbuser",
            applied=datetime.now(),
        ).execute()


def migrate_7_to_8():
    """
    Migrate between schema version 7 and 8.
    """

    with DATABASE.atomic():
        if "breeding" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=8,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("breeding")]

        if "breeding_herd_id" not in cols:
            # Go through.
            migrate(DATABASE_MIGRATOR.add_column("breeding", "breeding_herd_id", IntegerField(default=1)))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=8,
            comment="Add breerding_herd_id to breeding",
            applied=datetime.now(),
        ).execute()


def migrate_8_to_9():
    """
    Migrate between schema version 8 and 9 .
    added litter6w
    """

    with DATABASE.atomic():
        if "breeding" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=9,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("breeding")]

        if "litter_size6w" not in cols:
            # Go through.
            migrate(DATABASE_MIGRATOR.add_column("breeding", "litter_size6w", IntegerField(null=True)))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=9,
            comment="Add breerding_litter_size6w to breeding",
            applied=datetime.now(),
        ).execute()


def migrate_9_to_10():
    """
    Migrate between schema version 9 and 10.
    """
    with DATABASE.atomic():
        if "individual" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=10,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("individual")]

        if "has_photo" not in cols:
            migrate(
                DATABASE_MIGRATOR.add_column(
                    "individual",
                    "has_photo",
                    BooleanField(null=True, default=False),
                )
            )
        SchemaHistory.insert(  # pylint: disable=E1120
            version=10,
            comment="Add has_photo to individual",
            applied=datetime.now(),
        ).execute()


def migrate_10_to_11():
    """
    Migrate between schema version 10 and 11.
    """
    with DATABASE.atomic():
        if "hbuser" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(  # pylint: disable=E1120
                version=11,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("hbuser")]

        if "last_active" not in cols:
            # Go through hbuser and add last_active
            migrate(
                DATABASE_MIGRATOR.add_column(
                    "hbuser",
                    "last_active",
                    DateTimeField(default=datetime.now),
                )
            )
        SchemaHistory.insert(  # pylint: disable=E1120
            version=11,
            comment="Add last_active to hbuser",
            applied=datetime.now(),
        ).execute()


def migrate_11_to_12():
    """
    Migrate the database schema from version 11 to version 12.

    This migration performs the following steps:
    1. Checks if the "herd" table exists in the database.
    2. If the "herd" table does not exist, logs the migration as skipped.
    3. If the "herd" table exists, checks if the columns "bank_account_number",
       "bank_account_number_privacy", "bank_name", and "bank_name_privacy" are present.
    4. If the columns are not present, adds them to the "herd" table with the specified
       properties.
    5. Logs the migration as applied with a comment.

    The added columns are:
    - bank_account_number: TextField, nullable
    - bank_account_number_privacy: CharField with a max length of 15, nullable, default 'private'
    - bank_name: TextField, nullable
    - bank_name_privacy: CharField with a max length of 15, nullable, default 'private'
    """
    with DATABASE.atomic():
        if "herd" not in DATABASE.get_tables():
            # Can't run migration
            SchemaHistory.insert(
                version=12,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("herd")]

        if "bank_account_number" not in cols:
            migrate(
                DATABASE_MIGRATOR.add_column("herd", "bank_account_number", TextField(null=True)),
                DATABASE_MIGRATOR.add_column(
                    "herd",
                    "bank_account_number_privacy",
                    CharField(15, null=True, default="private"),
                ),
                DATABASE_MIGRATOR.add_column("herd", "bank_name", TextField(null=True)),
                DATABASE_MIGRATOR.add_column(
                    "herd",
                    "bank_name_privacy",
                    CharField(15, null=True, default="private"),
                ),
            )

        SchemaHistory.insert(
            version=12,
            comment="Add bank account fields to herd",
            applied=datetime.now(),
        ).execute()


def migrate_12_to_13():
    """
    Migrate between schema version 12 and 13.
    Adds a 'version' field to the 'yearlyherdreport' table.
    """
    with DATABASE.atomic():
        if "yearlyherdreport" not in DATABASE.get_tables():
            # Can't run migration if the table doesn't exist
            SchemaHistory.insert(
                version=13,
                comment="YearlyHerdReport table does not exist; skipping migration.",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("yearlyherdreport")]

        if "version" not in cols:
            migrate(
                DATABASE_MIGRATOR.add_column(
                    "yearlyherdreport",
                    "version",
                    CharField(null=True),
                )
            )
            SchemaHistory.insert(
                version=13,
                comment="Added 'version' field to 'yearlyherdreport' table",
                applied=datetime.now(),
            ).execute()
        else:
            # If the column already exists, update the schema history
            SchemaHistory.insert(
                version=13,
                comment="'version' field already exists in 'yearlyherdreport'",
                applied=datetime.now(),
            ).execute()


def migrate_13_to_14():
    """
    Migrate between schema version 13 and 14.
    Add YearlyReportRound model, link YearlyHerdReport to it, and remove GenebankReport.
    """
    with DATABASE.atomic():
        # Create YearlyReportRound table if it doesn't exist
        if not YearlyReportRound.table_exists():
            YearlyReportRound.create_table()

        # Add 'round' field to YearlyHerdReport
        cols = [x.name for x in DATABASE.get_columns("yearlyherdreport")]
        if "round_id" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("yearlyherdreport", "round_id", IntegerField(null=True)))
            # Optionally, add foreign key constraint if supported

        # Remove GenebankReport table if it exists
        if "genebankreport" in DATABASE.get_tables():
            DATABASE.execute_sql("DROP TABLE IF EXISTS genebankreport;")

        SchemaHistory.insert(
            version=14,
            comment="Added YearlyReportRound, linked YearlyHerdReport to it, removed GenebankReport",
            applied=datetime.now(),
        ).execute()


def migrate_14_to_15():
    """
    Migrate between schema version 14 and 15.
    Add profile picture support with Google integration.
    """
    with DATABASE.atomic():
        # Check existing columns in hbuser table
        cols = [x.name for x in DATABASE.get_columns("hbuser")]

        # Add profile_picture column
        if "profile_picture" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("hbuser", "profile_picture", TextField(null=True)))

        # Add google_picture column
        if "google_picture" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("hbuser", "google_picture", TextField(null=True)))

        # Add google_name column
        if "google_name" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("hbuser", "google_name", TextField(null=True)))

        # Add google_email column
        if "google_email" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("hbuser", "google_email", TextField(null=True)))

        # Add use_google_picture column
        if "use_google_picture" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("hbuser", "use_google_picture", BooleanField(default=True)))

        # Record migration in schema history
        SchemaHistory.insert(
            version=15,
            comment="Added profile picture support with Google integration",
            applied=datetime.now(),
        ).execute()


def migrate_15_to_16():
    """Add GeneticMetricsHistory table for trend data."""
    with DATABASE.atomic():
        DATABASE.create_tables([GeneticMetricsHistory])
        SchemaHistory.insert(
            version=16,
            comment="Add GeneticMetricsHistory table",
            applied=datetime.now(),
        ).execute()


def migrate_16_to_17():
    """Add updated_at columns to Individual and Breeding for cache invalidation."""
    with DATABASE.atomic():
        cols = [c.name for c in DATABASE.get_columns("individual")]
        if "updated_at" not in cols:
            migrate(
                DATABASE_MIGRATOR.add_column(
                    "individual",
                    "updated_at",
                    DateTimeField(default=datetime.now, null=True),
                )
            )
            DATABASE.execute_sql("UPDATE individual SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

        cols = [c.name for c in DATABASE.get_columns("breeding")]
        if "updated_at" not in cols:
            migrate(
                DATABASE_MIGRATOR.add_column(
                    "breeding",
                    "updated_at",
                    DateTimeField(default=datetime.now, null=True),
                )
            )
            DATABASE.execute_sql("UPDATE breeding SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

        SchemaHistory.insert(  # pylint: disable=E1120
            version=17,
            comment="Add updated_at to Individual and Breeding for cache invalidation",
            applied=datetime.now(),
        ).execute()


# pk_col, snapshot_excluded, change_detection_excluded
#   snapshot_excluded:         value stripped from old_data/new_data snapshots;
#                              the change is still detected and listed in
#                              changed_fields (fact-not-value semantics)
#   change_detection_excluded: column ignored entirely; an UPDATE touching
#                              only these columns emits NO audit row
AUDITED_TABLES = {
    "individual": ("individual_id", [], ["updated_at"]),
    "breeding": ("breeding_id", [], ["updated_at"]),
    "bunny": ("bunny_id", [], ["updated_at"]),  # from develop (22→23 roster)
    "herd": ("herd_id", list(HERD_CONTACT_COLUMNS), []),
    "weight": ("weight_id", [], []),
    "bodyfat": ("bodyfat_id", [], []),
    "individualdisease": ("individual_disease_id", [], []),
    "herd_tracking": ("herd_tracking_id", [], []),
    "color": ("color_id", [], []),
    # password_hash was dropped in schema v6 but stays snapshot-excluded as
    # belt-and-suspenders for any pre-v6 audit rows.
    # name_on_check_page (stamboken #6): a change of only her check page choice writes no audit row, which would copy
    # the account's name and e-mail, also when anonymisation switches it off. The app log records her own choices.
    "hbuser": ("user_id", ["password_hash"], ["last_active", "name_on_check_page"]),
    # New in Phase 17:
    "genebank": ("genebank_id", [], []),  # name edits need a trail
    "authenticators": ("auth_id", ["auth_data"], []),
}


# Append-only audit_log (NFR-S8), re-created by every path that lifts it (migration 28 keeps its own literal).
AUDIT_LOG_NO_UPDATE_RULE = "CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING"

# Only rows still holding an IP address, so the nightly purge reads one day of rows once it has caught up.
AUDIT_IP_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_audit_log_ip_retention
        ON audit_log (changed_at, id) WHERE ip_address IS NOT NULL
"""


def _create_audit_table_and_triggers():
    """
    Create the audit_log table (if missing) via raw SQL DDL, then create or
    replace the audit trigger function and attach triggers to all tracked
    tables. Idempotent — safe to call multiple times.

    Skipped entirely on SQLite (triggers and JSONB are PostgreSQL-only).
    """
    if isinstance(DATABASE, SqliteDatabase):
        return

    # Create audit_log table with correct PG-specific types
    DATABASE.execute_sql("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              bigserial PRIMARY KEY,
            schema_name     text NOT NULL DEFAULT 'public',
            table_name      text NOT NULL,
            record_id       text NOT NULL,
            operation       text NOT NULL,
            old_data        jsonb,
            new_data        jsonb,
            changed_fields  text[],
            changed_by      text,
            ip_address      text,
            changed_at      timestamptz NOT NULL DEFAULT now(),
            transaction_id  bigint DEFAULT txid_current()
        );
        CREATE INDEX IF NOT EXISTS idx_audit_log_table_record
            ON audit_log (table_name, record_id);
        CREATE INDEX IF NOT EXISTS idx_audit_log_changed_at
            ON audit_log (changed_at);
        CREATE INDEX IF NOT EXISTS idx_audit_log_changed_by
            ON audit_log (changed_by);
    """)
    DATABASE.execute_sql(AUDIT_IP_INDEX_SQL)

    # Append-only: block UPDATE/DELETE on audit_log (NFR-S8)
    DATABASE.execute_sql(f"""
        DO $$ BEGIN
            {AUDIT_LOG_NO_UPDATE_RULE};
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    DATABASE.execute_sql("""
        DO $$ BEGIN
            CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log
                DO INSTEAD NOTHING;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Split-exclusion trigger function (all three branches
    # strip snapshot_excluded uniformly).
    #
    # CREATE TRIGGER arguments must be string constants (the
    # Postgres grammar rejects array expressions like ARRAY['x']::TEXT[]
    # at CREATE-TRIGGER parse time). We pass comma-
    # separated column lists and split them here. NB: string_to_array('',
    # ',') returns ARRAY[''], not an empty array, so branch explicitly.
    # Column names in AUDITED_TABLES are ASCII identifiers — no escaping
    # concern.
    DATABASE.execute_sql("""
        CREATE OR REPLACE FUNCTION audit_trigger_func()
        RETURNS TRIGGER AS $$
        DECLARE
            snapshot_excluded  text[] := CASE WHEN TG_ARGV[0] = '' THEN ARRAY[]::text[]
                                              ELSE string_to_array(TG_ARGV[0], ',') END;
            detection_excluded text[] := CASE WHEN TG_ARGV[1] = '' THEN ARRAY[]::text[]
                                              ELSE string_to_array(TG_ARGV[1], ',') END;
            pk_col       text := TG_ARGV[2];
            old_j        jsonb;
            new_j        jsonb;
            changed_cols text[] := ARRAY[]::text[];
            col          text;
            rec_id       text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                new_j := to_jsonb(NEW);
                rec_id := new_j ->> pk_col;
                -- Strip snapshot-excluded values; the fact stays in
                -- changed_fields (fact-not-value semantics).
                FOREACH col IN ARRAY snapshot_excluded LOOP
                    new_j := new_j - col;
                END LOOP;
                SELECT COALESCE(array_agg(k), ARRAY[]::text[]) INTO changed_cols
                FROM jsonb_object_keys(to_jsonb(NEW)) AS k
                WHERE k <> ALL(detection_excluded);

                INSERT INTO audit_log
                    (table_name, record_id, operation, new_data,
                     changed_fields, changed_by, ip_address)
                VALUES
                    (TG_TABLE_NAME, rec_id, 'INSERT', new_j, changed_cols,
                     nullif(current_setting('audit.user', true), ''),
                     nullif(current_setting('audit.ip', true), ''));
                RETURN NEW;

            ELSIF TG_OP = 'UPDATE' THEN
                old_j := to_jsonb(OLD);
                new_j := to_jsonb(NEW);

                -- Change detection runs BEFORE snapshot stripping, so a
                -- change to a snapshot-excluded column is still detected
                -- (the earlier code stripped first).
                --
                -- Compare via the pre-computed old_j/new_j (each == to_jsonb of
                -- the row, assigned just above) instead of calling to_jsonb(OLD)
                -- /to_jsonb(NEW) per column: those rebuild the whole row every
                -- iteration → O(N^2) per update. The loop source is
                -- materialised once, and only detection_excluded columns (which
                -- CONTINUE before the comparison) are removed from old_j/new_j,
                -- so every compared column still reads its true value.
                FOR col IN SELECT key FROM jsonb_each(new_j)
                LOOP
                    IF col = ANY(detection_excluded) THEN
                        -- Not compared, not recorded, and dropped from BOTH
                        -- snapshots (updated_at / last_active never appear).
                        old_j := old_j - col;
                        new_j := new_j - col;
                        CONTINUE;
                    END IF;
                    IF old_j -> col IS DISTINCT FROM new_j -> col THEN
                        changed_cols := array_append(changed_cols, col);
                    END IF;
                END LOOP;

                -- Only emit if a detection-tracked column actually changed.
                IF array_length(changed_cols, 1) IS NULL THEN
                    RETURN NEW;
                END IF;

                FOREACH col IN ARRAY snapshot_excluded LOOP
                    old_j := old_j - col;
                    new_j := new_j - col;
                END LOOP;

                rec_id := to_jsonb(OLD) ->> pk_col;

                INSERT INTO audit_log
                    (table_name, record_id, operation,
                     old_data, new_data, changed_fields,
                     changed_by, ip_address)
                VALUES
                    (TG_TABLE_NAME, rec_id, 'UPDATE',
                     old_j, new_j, changed_cols,
                     nullif(current_setting('audit.user', true), ''),
                     nullif(current_setting('audit.ip', true), ''));
                RETURN NEW;

            ELSIF TG_OP = 'DELETE' THEN
                old_j := to_jsonb(OLD);
                rec_id := old_j ->> pk_col;
                FOREACH col IN ARRAY snapshot_excluded LOOP
                    old_j := old_j - col;
                END LOOP;
                SELECT COALESCE(array_agg(k), ARRAY[]::text[]) INTO changed_cols
                FROM jsonb_object_keys(to_jsonb(OLD)) AS k
                WHERE k <> ALL(detection_excluded);

                INSERT INTO audit_log
                    (table_name, record_id, operation, old_data,
                     changed_fields, changed_by, ip_address)
                VALUES
                    (TG_TABLE_NAME, rec_id, 'DELETE', old_j, changed_cols,
                     nullif(current_setting('audit.user', true), ''),
                     nullif(current_setting('audit.ip', true), ''));
                RETURN OLD;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Attach triggers to each tracked table.
    #
    # IMPORTANT: the trigger NAME is `audit_trigger`,
    # shared with the legacy installation. Do NOT rename to a per-table
    # `audit_{table}_trigger` — the legacy trigger would stay installed
    # calling the NEW function with the OLD arg shape, causing failed
    # writes or double-audit. Same name → replaced, never stacked.
    #
    # CREATE OR REPLACE TRIGGER (Postgres 14+; herdbook runs 18)
    # is one atomic DDL statement — no DROP→CREATE window where a write
    # would bypass auditing.
    #
    # Skip tables that don't exist yet (from develop): during migration replay
    # this runs at 17→18, before later migrations have created newer tracked
    # tables (e.g. bunny, created at 22→23, which re-runs this function to
    # attach the skipped trigger).
    existing_tables = set(DATABASE.get_tables())
    for table, (pk_col, snapshot_excluded, change_detection_excluded) in AUDITED_TABLES.items():
        if table not in existing_tables:
            continue
        snap_arg = ",".join(snapshot_excluded)  # "" when empty
        det_arg = ",".join(change_detection_excluded)  # "" when empty
        DATABASE.execute_sql(f"""
            CREATE OR REPLACE TRIGGER audit_trigger
            AFTER INSERT OR UPDATE OR DELETE ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_func(
                '{snap_arg}', '{det_arg}', '{pk_col}'
            )
        """)


def migrate_17_to_18():
    """Add audit_log table and attach audit triggers to tracked tables."""
    logger.info("Migrating to schema version 18")

    with DATABASE.atomic():
        _create_audit_table_and_triggers()

        SchemaHistory.insert(
            version=18,
            comment="Add audit_log table and triggers",
            applied=datetime.now(),
        ).execute()


def migrate_18_to_19():
    """Add indexes for paginated individuals endpoint (story 3.4 performance)."""
    with DATABASE.atomic():
        indexes = [
            ("idx_individual_name", "individual", '"name" COLLATE "sv-SE-x-icu"'),
            ("idx_individual_sex", "individual", "sex"),
            ("idx_individual_death", "individual", "origin_herd_id, death_date"),
            (
                "idx_herdtracking_individual_date",
                "herd_tracking",
                "individual_id, herd_tracking_date DESC, herd_tracking_id DESC",
            ),
        ]
        for idx_name, table, columns in indexes:
            DATABASE.execute_sql(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ({columns})')

        SchemaHistory.insert(  # pylint: disable=E1120
            version=19,
            comment="Add indexes for paginated individuals performance",
            applied=datetime.now(),
        ).execute()


def migrate_19_to_20():
    """Add v2_prod_access boolean for per-user v2-prod promotion."""
    with DATABASE.atomic():
        cols = [x.name for x in DATABASE.get_columns("hbuser")]
        if "v2_prod_access" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("hbuser", "v2_prod_access", BooleanField(default=False)))
        SchemaHistory.insert(
            version=20,
            comment="Add v2_prod_access for per-user v2-prod promotion",
            applied=datetime.now(),
        ).execute()


def migrate_20_to_21():
    """Add DigitalCertificateV2 table and Individual.foot_ring for v2 certificates."""
    with DATABASE.atomic():
        DATABASE.create_tables([DigitalCertificateV2])

        cols = [x.name for x in DATABASE.get_columns("individual")]
        if "foot_ring" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("individual", "foot_ring", CharField(20, null=True)))

        SchemaHistory.insert(
            version=21,
            comment="Add DigitalCertificateV2 table and Individual.foot_ring for v2 certificates",
            applied=datetime.now(),
        ).execute()


def _create_demo_sync_status_table():
    """Create the demo_sync_status telemetry table. Idempotent.

    Raw-SQL-managed, not a Peewee model: TIMESTAMPTZ columns match the spec
    DDL exactly (DateTimeField would create timestamp WITHOUT time zone).
    Written by the host-side scripts/sync-demo-db.sh; read via raw SQL by
    GET /api/v2/admin/sync-status. NOT in AUDITED_TABLES — operational
    telemetry, not member data.
    """
    if isinstance(DATABASE, SqliteDatabase):
        return
    DATABASE.execute_sql("""
        CREATE TABLE IF NOT EXISTS demo_sync_status (
            id           SERIAL PRIMARY KEY,
            started_at   TIMESTAMPTZ NOT NULL,
            finished_at  TIMESTAMPTZ NULL,
            success      BOOLEAN NULL,
            detail       TEXT NULL,
            rows_synced  INTEGER NULL
        );
    """)


def _apply_phase17_schema_changes():
    """Idempotent DDL body of migration 27→28.

    Extracted from migrate_27_to_28() so tests can re-run it against an
    already-migrated database (the pytest stack bootstraps SchemaHistory at
    CURRENT_SCHEMA_VERSION, so the full migration — with its SchemaHistory
    PK insert — never replays there).
    """
    cols = [x.name for x in DATABASE.get_columns("hbuser")]
    if "is_active" not in cols:
        # NOT NULL with default=True — playhouse backfills existing rows TRUE.
        migrate(DATABASE_MIGRATOR.add_column("hbuser", "is_active", BooleanField(default=True)))
    _create_demo_sync_status_table()
    # Rewritten split-exclusion audit_trigger_func + re-attach to every
    # AUDITED_TABLES entry — first-time attach for genebank and
    # authenticators, updated exclude args for hbuser.
    _create_audit_table_and_triggers()


def _run_phase17_credential_redaction():
    """One-time historical credential redaction. Idempotent
    in effect (a second run matches zero rows and writes a zero-count
    marker). DROP RULE → DO block (UPDATE + GET DIAGNOSTICS + marker) →
    CREATE RULE; the rule is only absent while the redaction runs.

    audit_log is append-only in spirit — this is the ONE deliberate
    exception, traced via the marker row. Rollback is impossible by
    design: the hashes are gone, and were never audit-relevant.
    """
    DATABASE.execute_sql("""
        DROP RULE IF EXISTS audit_log_no_update ON audit_log;
        DO $$
        DECLARE
            auth_affected bigint;
            hash_affected bigint;
            total         bigint;
        BEGIN
            -- 2a) Primary target: authenticators.auth_data.
            --     VALUES only — changed_fields behåller kolumnnamnet
            --     (fact-not-value). Namnet läcker
            --     inget, bevarar spåret "en återställning skedde", och
            --     rader skrivna av den NYA triggern under deploy-fönstret
            --     bär namnet legitimt.
            UPDATE audit_log
            SET old_data       = old_data - 'auth_data',
                new_data       = new_data - 'auth_data'
            WHERE table_name = 'authenticators'
              AND (old_data ? 'auth_data'
                   OR new_data ? 'auth_data');
            GET DIAGNOSTICS auth_affected = ROW_COUNT;

            -- 2b) Belt: legacy hbuser.password_hash. Expected 0 on
            --     any DB migrated past schema v6; guards restored pre-v6
            --     archival data.
            UPDATE audit_log
            SET old_data       = old_data - 'password_hash',
                new_data       = new_data - 'password_hash'
            WHERE table_name = 'hbuser'
              AND (old_data ? 'password_hash'
                   OR new_data ? 'password_hash');
            GET DIAGNOSTICS hash_affected = ROW_COUNT;

            total := auth_affected + hash_affected;
            RAISE NOTICE
                'Phase 17 credential redaction affected %% audit_log rows '
                '(auth_data=%%, password_hash=%%).',
                total, auth_affected, hash_affected;

            -- 3) Marker row — same transaction, receipt of the exception.
            INSERT INTO audit_log
                (table_name, record_id, operation, old_data, new_data,
                 changed_fields, changed_by, changed_at)
            VALUES
                ('audit_log', 'migration-28-credential-redaction', 'UPDATE',
                 NULL,
                 jsonb_build_object(
                     'note', 'Redacted historical credential material from audit_log.',
                     'reason', 'Phase 17 §4.1.c one-time cleanup.',
                     'auth_data_rows', auth_affected,
                     'password_hash_rows', hash_affected,
                     'total_rows', total),
                 ARRAY['auth_data', 'password_hash']::TEXT[],
                 'migration-28',
                 NOW());
        END;
        $$;
        CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
    """)
    # Fail loudly if anything leaked through.
    # Snapshots ONLY — changed_fields bär legitimt kolumnnamnet på rader
    # skrivna av den nya fact-not-value-triggern (t.ex. under rolling
    # deploy); en ANY(changed_fields)-arm här skulle krascha migrationen
    # på helt korrekta rader.
    leftover_auth = DATABASE.execute_sql(
        "SELECT COUNT(*) FROM audit_log "
        "WHERE table_name = 'authenticators' "
        "  AND (old_data ? 'auth_data' OR new_data ? 'auth_data')"
    ).fetchone()[0]
    leftover_hash = DATABASE.execute_sql(
        "SELECT COUNT(*) FROM audit_log "
        "WHERE table_name = 'hbuser' "
        "  AND (old_data ? 'password_hash' OR new_data ? 'password_hash')"
    ).fetchone()[0]
    if leftover_auth or leftover_hash:
        raise RuntimeError(
            f"Phase 17 credential redaction left {leftover_auth} authenticators "
            f"rows and {leftover_hash} hbuser rows with unredacted credentials. "
            "Refusing to declare the migration complete."
        )


def migrate_27_to_28():
    """Phase 17: hbuser.is_active, demo_sync_status,
    split-exclusion audit triggers."""
    with DATABASE.atomic():
        _apply_phase17_schema_changes()
        # AFTER the trigger rewrite so concurrent password
        # resets land under the new split-exclusion semantics first.
        _run_phase17_credential_redaction()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=28,
            comment="Phase 17: split-exclusion audit triggers "
            "(genebank+authenticators), hbuser.is_active, demo_sync_status",
            applied=datetime.now(),
        ).execute()


def _reconcile_member_user_links():
    """Preflight for idx_member_user_unique (Phase 19): a user
    linked to several person rows keeps ONE — active (end_date IS NULL)
    first, then huvudmedlem, then the lowest id — and is detached from the
    rest. Ids are logged, never names. No-op on a clean database."""
    if "member" not in DATABASE.get_tables():
        return
    duplicates = DATABASE.execute_sql(
        'SELECT "user_id" FROM "member" WHERE "user_id" IS NOT NULL GROUP BY "user_id" HAVING COUNT(*) > 1'
    ).fetchall()
    for (user_id,) in duplicates:
        rows = DATABASE.execute_sql(
            'SELECT "member_id" FROM "member" WHERE "user_id" = %s '
            'ORDER BY ("end_date" IS NULL) DESC, ("role" = \'huvudmedlem\') DESC, "member_id" ASC',
            (user_id,),
        ).fetchall()
        keep, *detach = [row[0] for row in rows]
        DATABASE.execute_sql(
            'UPDATE "member" SET "user_id" = NULL WHERE "member_id" = ANY(%s)',
            (detach,),
        )
        logger.warning(
            "Phase 19 link preflight: user %s linked to member rows %s — kept %s, detached %s",
            user_id,
            [keep, *detach],
            keep,
            detach,
        )


def _apply_phase19_schema_changes():
    """Idempotent DDL body of migration 28→29 (Phase 19).

    Adds only absent columns, backfills + drops membership.postal_address
    only while it exists, then (re)creates the member indexes. Safe to
    replay on a bootstrapped or already-migrated database —
    test_database.py replays the full chain against the pytest stack.
    """
    with DATABASE.atomic():
        membership_cols = {c.name for c in DATABASE.get_columns("membership")}
        if "postal_code" not in membership_cols:
            migrate(DATABASE_MIGRATOR.add_column("membership", "postal_code", CharField(max_length=10, null=True)))
        if "city" not in membership_cols:
            migrate(DATABASE_MIGRATOR.add_column("membership", "city", CharField(max_length=100, null=True)))
        if "postal_address" in membership_cols:
            rows = DATABASE.execute_sql(
                'SELECT "membership_id", "postal_address" FROM "membership" '
                'WHERE "postal_address" IS NOT NULL AND btrim("postal_address") <> \'\''
            ).fetchall()
            for membership_id, raw in rows:
                postal_code, city = split_postal_address(raw)
                if postal_code is None:
                    logger.warning(
                        "Phase 19 backfill: membership %s Postadress did not parse — kept in city",
                        membership_id,
                    )
                DATABASE.execute_sql(
                    'UPDATE "membership" SET "postal_code" = %s, "city" = %s WHERE "membership_id" = %s',
                    (postal_code, city, membership_id),
                )
            migrate(DATABASE_MIGRATOR.drop_column("membership", "postal_address"))

        application_cols = {c.name for c in DATABASE.get_columns("member_application")}
        if "postal_code" not in application_cols:
            migrate(
                DATABASE_MIGRATOR.add_column("member_application", "postal_code", CharField(max_length=10, null=True))
            )
        if "city" not in application_cols:
            migrate(DATABASE_MIGRATOR.add_column("member_application", "city", CharField(max_length=100, null=True)))

        _reconcile_member_user_links()  # ONLY here — init() must never rewrite links
        _create_member_indexes()  # partial unique index — the same helper init() calls on fresh databases


def migrate_28_to_29():
    """Phase 19: structured postal address + one-user-one-person-row invariant."""
    with DATABASE.atomic():
        _apply_phase19_schema_changes()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=29,
            comment="Phase 19: membership.postal_code/city (backfilled from postal_address, dropped), "
            "member_application.postal_code/city, idx_member_user_unique",
            applied=datetime.now(),
        ).execute()


def _create_breeding_litter_number_index():
    """
    Create the unique partial index that backstops concurrent litter_number
    assignment (register_birth's savepoint retry, import's 409 mapping).
    Idempotent — called from both init() and migrate_21_to_22 so fresh
    bootstraps and migrated databases converge.

    Skipped on SQLite (EXTRACT/INTERVAL are PostgreSQL-only).
    """
    if isinstance(DATABASE, SqliteDatabase):
        return

    DATABASE.execute_sql("""
        CREATE UNIQUE INDEX IF NOT EXISTS "idx_breeding_herd_year_litter"
        ON "breeding" (
            breeding_herd_id,
            EXTRACT(YEAR FROM COALESCE(birth_date, breed_date + INTERVAL '30 days')),
            litter_number
        )
        WHERE litter_number IS NOT NULL
    """)


def _create_herd_tracking_guards():
    """
    Idempotent DB guards for herd_tracking: created_at
    default, kind + void CHECKs and the partial indexes. Called from init() and
    migrate_29_to_30 so fresh bootstraps and migrated databases converge.
    Skipped on SQLite.
    """
    if isinstance(DATABASE, SqliteDatabase):
        return
    sql = DATABASE.execute_sql
    sql('ALTER TABLE "herd_tracking" ALTER COLUMN "created_at" SET DEFAULT now()')
    checks = (
        ("herd_tracking_kind_check", "kind IN (" + ", ".join(f"'{kind}'" for kind in HT_KINDS) + ")"),
        (
            "herd_tracking_void_fields_check",
            "(voided_at IS NULL AND voided_by_user_id IS NULL AND voided_operation_id IS NULL "
            "AND voided_reason IS NULL) OR (voided_at IS NOT NULL AND voided_by_user_id IS NOT NULL "
            "AND voided_operation_id IS NOT NULL AND btrim(coalesce(voided_reason, '')) <> '')",
        ),
    )
    for name, check in checks:
        sql(
            f"""DO $$ BEGIN
                    ALTER TABLE "herd_tracking" ADD CONSTRAINT "{name}" CHECK ({check});
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;"""
        )
    sql(
        'CREATE INDEX IF NOT EXISTS "idx_herdtracking_active_latest" ON "herd_tracking" '
        "(individual_id, herd_tracking_date DESC, (kind = 'BIRTH'), herd_tracking_id DESC) "
        "WHERE voided_at IS NULL"
    )
    sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_herdtracking_one_birth" ON "herd_tracking" (individual_id) '
        "WHERE kind = 'BIRTH' AND voided_at IS NULL"
    )
    sql('CREATE INDEX IF NOT EXISTS "idx_herdtracking_operation" ON "herd_tracking" (operation_id)')
    sql(
        'CREATE INDEX IF NOT EXISTS "idx_herdtracking_voided_operation" ON "herd_tracking" '
        "(voided_operation_id) WHERE voided_operation_id IS NOT NULL"
    )
    sql(
        'CREATE INDEX IF NOT EXISTS "idx_herdtracking_restored_operation" ON "herd_tracking" '
        "(restored_operation_id) WHERE restored_operation_id IS NOT NULL"
    )
    sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_herdtracking_report_attestation" ON "herd_tracking" '
        "(individual_id, yearly_herd_report_id) WHERE yearly_herd_report_id IS NOT NULL AND voided_at IS NULL"
    )
    sql(
        """CREATE OR REPLACE FUNCTION herd_tracking_block_delete() RETURNS trigger AS $$
           BEGIN
               RAISE EXCEPTION 'DELETE på herd_tracking är inte tillåten — använd void'
                   USING ERRCODE = '42501';
           END;
           $$ LANGUAGE plpgsql"""
    )
    sql(
        'CREATE OR REPLACE TRIGGER "herd_tracking_no_delete" BEFORE DELETE ON "herd_tracking" '
        "FOR EACH ROW EXECUTE FUNCTION herd_tracking_block_delete()"
    )


_HT_V30_COLUMNS = (
    ("kind", "VARCHAR(20)"),
    ("operation_id", "UUID"),
    ("created_at", "TIMESTAMPTZ"),
    ("notes", "TEXT"),
    ("voided_at", "TIMESTAMPTZ"),
    ("voided_by_user_id", 'INTEGER REFERENCES "hbuser" ("user_id")'),
    ("voided_reason", "TEXT"),
    ("voided_operation_id", "UUID"),
    ("restored_operation_id", "UUID"),
    ("restored_at", "TIMESTAMPTZ"),
    ("yearly_herd_report_id", 'INTEGER REFERENCES "yearlyherdreport" ("yearly_herd_report_id")'),
    ("transfer_id", "INTEGER"),
    ("holder_contact_id", "INTEGER"),
)

# Positional classification: per individual in (date, id) order,
# the first row is BIRTH if it is in the origin herd, else TRANSFER; later rows are
# TRANSFER when the herd changes, else ATTESTATION. NULL herds compare as different.
_HT_V30_CLASSIFY = """
    WITH ordered AS (
        SELECT ht.herd_tracking_id AS id, ht.herd_id, i.origin_herd_id,
               ROW_NUMBER() OVER w AS pos,
               LAG(ht.herd_id) OVER w AS prev_herd_id
          FROM herd_tracking ht
          JOIN individual i ON i.individual_id = ht.individual_id
        WINDOW w AS (PARTITION BY ht.individual_id ORDER BY ht.herd_tracking_date, ht.herd_tracking_id)
    )
    UPDATE herd_tracking t
       SET kind = CASE
           WHEN o.pos = 1 AND o.herd_id IS NOT DISTINCT FROM o.origin_herd_id THEN 'BIRTH'
           WHEN o.pos = 1 THEN 'TRANSFER'
           WHEN o.herd_id IS DISTINCT FROM o.prev_herd_id THEN 'TRANSFER'
           ELSE 'ATTESTATION'
       END
      FROM ordered o
     WHERE o.id = t.herd_tracking_id AND t.kind IS NULL
"""


def _apply_herd_tracking_v30():
    """
    Idempotent body of migrate_29_to_30: add the
    columns, backfill set-based with the audit trigger disabled (needs table owner,
    not superuser; DDL is transactional), SET NOT NULL, swap the index, guards.
    A no-op on the final schema (TestDatabaseMigration replays the whole chain).
    Skipped on SQLite.
    """
    if isinstance(DATABASE, SqliteDatabase):
        return
    sql = DATABASE.execute_sql
    existing = {c.name for c in DATABASE.get_columns("herd_tracking")}
    for name, ddl in _HT_V30_COLUMNS:
        if name not in existing:
            sql(f'ALTER TABLE "herd_tracking" ADD COLUMN "{name}" {ddl}')
    # Peewee's create_table makes these FK indexes on a fresh bootstrap — match them.
    sql('CREATE INDEX IF NOT EXISTS "herdtracking_voided_by_user_id" ON "herd_tracking" ("voided_by_user_id")')
    sql('CREATE INDEX IF NOT EXISTS "herdtracking_yearly_herd_report_id" ON "herd_tracking" ("yearly_herd_report_id")')

    audit_trigger = sql(
        "SELECT 1 FROM pg_trigger WHERE tgrelid = 'herd_tracking'::regclass AND tgname = 'audit_trigger'"
    ).fetchone()
    if audit_trigger:
        sql('ALTER TABLE "herd_tracking" DISABLE TRIGGER "audit_trigger"')
    if "audit_log" in DATABASE.get_tables():
        sql(
            """UPDATE herd_tracking t SET created_at = a.first_at
                 FROM (SELECT record_id, MIN(changed_at) AS first_at FROM audit_log
                        WHERE table_name = 'herd_tracking' AND operation = 'INSERT'
                        GROUP BY record_id) a
                WHERE t.created_at IS NULL AND a.record_id = t.herd_tracking_id::text"""
        )
    sql(
        "UPDATE herd_tracking SET created_at = herd_tracking_date::timestamp AT TIME ZONE 'Europe/Stockholm' "
        "WHERE created_at IS NULL"
    )
    sql("UPDATE herd_tracking SET operation_id = gen_random_uuid() WHERE operation_id IS NULL")
    sql(_HT_V30_CLASSIFY)
    if audit_trigger:
        sql('ALTER TABLE "herd_tracking" ENABLE TRIGGER "audit_trigger"')

    sql(
        'ALTER TABLE "herd_tracking" ALTER COLUMN "kind" SET NOT NULL, '
        'ALTER COLUMN "operation_id" SET NOT NULL, ALTER COLUMN "created_at" SET NOT NULL'
    )
    sql('DROP INDEX IF EXISTS "idx_herdtracking_individual_date"')
    _create_herd_tracking_guards()


def migrate_29_to_30():
    """Phase 999.5: herd_tracking kind + void + operations."""
    with DATABASE.atomic():
        _apply_herd_tracking_v30()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=30,
            comment="999.5: herd_tracking kind/void/operation columns, backfill, guards, active-latest index",
            applied=datetime.now(),
        ).execute()


# Breeding first: the guards' DDL then locks breeding before individual.
_GENETICS_UPDATE_COLUMNS = {
    "breeding": ("father_id", "mother_id", "breeding_herd_id", "birth_date"),
    "individual": (
        "breeding_id",
        "origin_herd_id",
        "number",
        "sex",
        "death_date",
        "death_note",
        "castration_date",
        "certificate",
        "digital_certificate",
        "voided",
    ),
    "herd": ("is_active", "genebank_id", "herd"),
    "yearlyreportround": ("end_date", "report_year"),
    "herd_tracking": None,  # every column
}


def read_genetics_version() -> int:
    """The committed global genetics version (bumped once per relevant transaction)."""
    return DATABASE.execute_sql("SELECT version FROM genetics_version WHERE id = 1").fetchone()[0]


def read_genetics_key() -> tuple[int, str]:
    """(version, epoch): the committed genetics version and this database's epoch, in one read."""
    version, epoch = DATABASE.execute_sql("SELECT version, epoch FROM genetics_version WHERE id = 1").fetchone()
    return version, epoch


def rotate_genetics_epoch() -> str:
    """Give the database a new genetics epoch and return it (``flask genetics rotate-epoch``).

    Run after the database was replaced (restore, demo sync): the copy brings back a
    version counter that can repeat a number a worker's snapshot is keyed on, and the
    epoch is what makes that snapshot rebuild. The memoized results need no epoch:
    they are keyed on the snapshot's content. The SQL
    function is the one the dump restore (stamboken-drift) and sync-demo-db.sh call through psql.
    """
    with DATABASE.atomic():
        return DATABASE.execute_sql("SELECT rotate_genetics_epoch()").fetchone()[0]


def _create_genetics_version_guards():
    """
    Global genetics version + deferred bump triggers.

    Called from init() and migrate_30_to_31 so a fresh bootstrap equals a migrated
    database. Rule: never SET CONSTRAINTS ... IMMEDIATE on these triggers before
    a transaction's domain writes and locks are done — the version row must stay
    the last lock a transaction takes. Skipped on SQLite.
    """
    if isinstance(DATABASE, SqliteDatabase):
        return
    sql = DATABASE.execute_sql
    sql(
        "CREATE TABLE IF NOT EXISTS genetics_version ("
        " id smallint PRIMARY KEY CHECK (id = 1),"
        " version bigint NOT NULL,"
        " changed_at timestamptz NOT NULL DEFAULT now())"
    )
    sql("INSERT INTO genetics_version (id, version) VALUES (1, 0) ON CONFLICT DO NOTHING")
    # Part of the snapshot key: a restored or copied database gets a new one.
    sql("ALTER TABLE genetics_version ADD COLUMN IF NOT EXISTS epoch text NOT NULL DEFAULT gen_random_uuid()::text")
    sql(
        """CREATE OR REPLACE FUNCTION rotate_genetics_epoch() RETURNS text
           LANGUAGE sql VOLATILE AS $$
             UPDATE genetics_version SET epoch = gen_random_uuid()::text WHERE id = 1 RETURNING epoch
           $$"""
    )
    sql(
        """CREATE OR REPLACE FUNCTION genetics_change() RETURNS trigger
           LANGUAGE plpgsql VOLATILE AS $$
           BEGIN
             IF coalesce(current_setting('herdbook.genetics_bumped', true), '') = '1' THEN
               RETURN NULL;
             END IF;
             UPDATE genetics_version SET version = version + 1, changed_at = now() WHERE id = 1;
             PERFORM set_config('herdbook.genetics_bumped', '1', true);
             RETURN NULL;
           END $$"""
    )
    tables = set(DATABASE.get_tables())
    for table, columns in _GENETICS_UPDATE_COLUMNS.items():
        if table not in tables:
            continue  # replay-safe: the guards rerun when the table exists
        events = "INSERT OR UPDATE OR DELETE" if columns is None else "INSERT OR DELETE"
        _create_trigger_if_missing(
            table,
            f"genetics_change_{table}_iud",
            f'CREATE CONSTRAINT TRIGGER "genetics_change_{table}_iud" AFTER {events} ON "{table}" '
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION genetics_change()",
        )
        if columns is not None:
            # WHEN is evaluated at the write, so irrelevant updates never queue an event.
            old = ", ".join(f"OLD.{c}" for c in columns)
            new = ", ".join(f"NEW.{c}" for c in columns)
            _create_trigger_if_missing(
                table,
                f"genetics_change_{table}_upd",
                f'CREATE CONSTRAINT TRIGGER "genetics_change_{table}_upd" AFTER UPDATE ON "{table}" '
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                f"WHEN (ROW({old}) IS DISTINCT FROM ROW({new})) EXECUTE FUNCTION genetics_change()",
            )


def _create_trigger_if_missing(table, name, ddl):
    """
    Create a trigger only when it is missing (constraint triggers have no CREATE OR REPLACE).

    Never drop + create on an existing database: init() would take table locks and leave a
    window in which a committing write gets no bump. An existing trigger costs one catalog
    read and no table lock; duplicate_object covers a concurrent creator. A changed
    definition needs its own migration that drops and recreates inside its atomic().
    """
    DATABASE.execute_sql(
        f"""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger
                                WHERE tgrelid = '"{table}"'::regclass AND tgname = '{name}') THEN
                    {ddl};
                END IF;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;"""
    )


def migrate_30_to_31():
    """Phase 999.8: global genetics version counter."""
    with DATABASE.atomic():
        _create_genetics_version_guards()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=31, comment="999.8: genetics_version + deferred bump triggers", applied=datetime.now()
        ).execute()


def migrate_31_to_32():
    """Phase 999.8: history keyed on report year, versioned."""
    with DATABASE.atomic():
        table = GeneticMetricsHistory._meta.table_name
        if table in DATABASE.get_tables():
            DATABASE.execute_sql(f'DELETE FROM "{table}"')  # derived; reconcile refills
            existing = {c.name for c in DATABASE.get_columns(table)}
            for name, fld in (
                ("report_year", IntegerField(default=0)),
                ("as_of", DateField(default=date(1970, 1, 1))),
                ("definition_version", IntegerField(default=0)),
                ("pedigree_version", BigIntegerField(default=0)),
                ("fge", FloatField(null=True)),
            ):
                if name not in existing:
                    migrate(DATABASE_MIGRATOR.add_column(table, name, fld))
            for idx in DATABASE.get_indexes(table):
                if idx.unique and idx.columns == ["genebank_id", "snapshot_date"]:
                    DATABASE.execute_sql(f'DROP INDEX IF EXISTS "{idx.name}"')
            GeneticMetricsHistory._schema.create_indexes(safe=True)  # same names as a fresh bootstrap
        GeneticsHistoryState.create_table(safe=True)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=32, comment="999.8: history per report year, versioned; history state", applied=datetime.now()
        ).execute()


def migrate_32_to_33():
    """The history watermark carries the algorithm version, so a formula fix recomputes stored years."""
    with DATABASE.atomic():
        table = GeneticsHistoryState._meta.table_name
        # A replay from below 32 creates the table from the current model, column included.
        if "algorithm_version" not in {c.name for c in DATABASE.get_columns(table)}:
            migrate(DATABASE_MIGRATOR.add_column(table, "algorithm_version", IntegerField(default=0)))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=33, comment="R035: genetics history algorithm version", applied=datetime.now()
        ).execute()


def migrate_33_to_34():
    """genetics_version gets a random epoch, part of the genetics memo key, and its rotate function."""
    with DATABASE.atomic():
        _create_genetics_version_guards()  # adds the column and function when missing; replay-safe
        SchemaHistory.insert(  # pylint: disable=E1120
            version=34, comment="R043: genetics epoch", applied=datetime.now()
        ).execute()


def migrate_34_to_35():
    """ADR-0017: the command log of individual writes."""
    with DATABASE.atomic():
        DATABASE.create_tables([IndividualCommand], safe=True)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=35, comment="ADR-0017: individual_command", applied=datetime.now()
        ).execute()


def migrate_35_to_36():
    """Individual.microchip: most rabbits are no longer ear-tattooed, they get a chip and a foot ring."""
    with DATABASE.atomic():
        if "microchip" not in [x.name for x in DATABASE.get_columns("individual")]:
            migrate(DATABASE_MIGRATOR.add_column("individual", "microchip", Individual.microchip))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=36, comment="Individual.microchip", applied=datetime.now()
        ).execute()


def migrate_36_to_37():
    """Optional billing address per membership, also collected by the application form."""
    with DATABASE.atomic():
        for model in (Membership, MemberApplication):
            table = model._meta.table_name
            existing = {c.name for c in DATABASE.get_columns(table)}
            for name in BILLING_FIELDS:
                if name not in existing:
                    migrate(DATABASE_MIGRATOR.add_column(table, name, getattr(model, name)))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=37, comment="membership/member_application billing address", applied=datetime.now()
        ).execute()


def migrate_37_to_38():
    """
    Data only (ADR-0019): before AssignPaperCertificate retired the row, a paper certificate replacing a digital
    one left the PDF row current, so verify and download kept answering for it. Retires those rows.

    A current row whose rabbit has no number at all is left alone and counted: the old code also removed the
    digital number on a blank paper number, and that certificate was never replaced. Its number is restored by
    hand from the history, not withdrawn here.
    """
    with DATABASE.atomic():
        lost = 0
        if "digitalcertificatev2" in DATABASE.get_tables():
            DATABASE.execute_sql(
                "UPDATE digitalcertificatev2 SET is_current = FALSE WHERE is_current AND individual_id IN "
                "(SELECT individual_id FROM individual "
                "WHERE digital_certificate IS NULL AND coalesce(certificate, '') <> '')"
            )
            lost = DATABASE.execute_sql(
                "SELECT count(*) FROM digitalcertificatev2 WHERE is_current AND individual_id IN "
                "(SELECT individual_id FROM individual "
                "WHERE digital_certificate IS NULL AND coalesce(certificate, '') = '')"
            ).fetchone()[0]
            if lost:
                logger.warning("migrate_37_to_38: %s current certificate PDF rows have lost their number", lost)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=38,
            comment=f"retire PDF rows of replaced digital certificates; {lost} current rows without a number left",
            applied=datetime.now(),
        ).execute()


def migrate_38_to_39():
    """Partial index for the nightly removal of audit_log IP addresses older than 12 months (purge_audit_ip)."""
    with DATABASE.atomic():
        if not isinstance(DATABASE, SqliteDatabase) and "audit_log" in DATABASE.get_tables():
            DATABASE.execute_sql(AUDIT_IP_INDEX_SQL)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=39, comment="audit_log IP retention index", applied=datetime.now()
        ).execute()


def migrate_39_to_40():
    """Issue #33: the bank details are always private, so reset any stored level."""
    with DATABASE.atomic():
        # The audit trigger would copy every account number into a new audit row without a user.
        audited = (
            not isinstance(DATABASE, SqliteDatabase)
            and DATABASE.execute_sql(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'herd'::regclass AND tgname = 'audit_trigger'"
            ).fetchone()
        )
        if audited:
            DATABASE.execute_sql('ALTER TABLE "herd" DISABLE TRIGGER "audit_trigger"')
        # NULL stays NULL (reads treat it as private).
        DATABASE.execute_sql(
            "UPDATE herd SET"
            " bank_account_number_privacy = CASE WHEN bank_account_number_privacy IS NULL THEN NULL ELSE 'private' END,"
            " bank_name_privacy = CASE WHEN bank_name_privacy IS NULL THEN NULL ELSE 'private' END"
            " WHERE bank_account_number_privacy <> 'private' OR bank_name_privacy <> 'private'"
        )
        if audited:
            DATABASE.execute_sql('ALTER TABLE "herd" ENABLE TRIGGER "audit_trigger"')
        SchemaHistory.insert(  # pylint: disable=E1120
            version=40, comment="herd bank privacy reset to private", applied=datetime.now()
        ).execute()


def migrate_40_to_41():
    """The outgoing mail queue (docs/mejl.md). Not audited: no addresses or texts, purged after 13 months."""
    with DATABASE.atomic():
        DATABASE.create_tables([MailMessage, MailAttempt, MailSender], safe=True)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=41, comment="mail queue: mail_message, mail_attempt, mail_sender", applied=datetime.now()
        ).execute()


def migrate_41_to_42():
    """The intake queue (docs/inkorg.md), and the Gmail reader's tables for a later part of it. Not audited."""
    with DATABASE.atomic():
        DATABASE.create_tables(INBOX_MODELS, safe=True)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=42, comment="intake queue: inbox_*, notice, notice_setting, gmail_*", applied=datetime.now()
        ).execute()


def migrate_42_to_43():
    """The intake queue's retention (docs/inkorg.md, "Gallring"): an original can be gone, and a document records the
    members it shows (seller and buyer), so an erasure finds it. A mailed item records whether Gmail authenticated
    its sender, the only one mail goes back to. The Gmail reader counts the runs a message failed in."""
    with DATABASE.atomic():
        DATABASE.execute_sql("ALTER TABLE inbox_document ALTER COLUMN original_path DROP NOT NULL")
        DATABASE.execute_sql("ALTER TABLE inbox_item ADD COLUMN IF NOT EXISTS sender_authenticated BOOLEAN")
        DATABASE.execute_sql(
            "ALTER TABLE gmail_processed ADD COLUMN IF NOT EXISTS failures SMALLINT NOT NULL DEFAULT 0"
        )
        for column in ("seller_member_id", "buyer_member_id"):
            DATABASE.execute_sql(
                f"ALTER TABLE inbox_document ADD COLUMN IF NOT EXISTS {column} INTEGER "
                "REFERENCES member (member_id) ON DELETE SET NULL"
            )
        _create_field_indexes(InboxDocument, "seller_member", "buyer_member")
        SchemaHistory.insert(  # pylint: disable=E1120
            version=43,
            comment="inbox_document: original_path nullable, seller and buyer members; "
            "inbox_item.sender_authenticated; gmail_processed.failures",
            applied=datetime.now(),
        ).execute()


def _create_buyer_contact_guards():
    """
    Idempotent: the buyer_contact table and herd_tracking.holder_contact_id as its FK, ON DELETE SET NULL, with the
    names a fresh bootstrap gives them. Called from init() and migrate_43_to_44. Skipped on SQLite.
    """
    if isinstance(DATABASE, SqliteDatabase):
        return
    BuyerContact.create_table(safe=True)
    # An earlier build of migration 44 tied the address to the consent (#111 dropped that); safe to repeat.
    DATABASE.execute_sql('ALTER TABLE "buyer_contact" DROP CONSTRAINT IF EXISTS "buyer_contact_address_needs_consent"')
    DATABASE.execute_sql(
        """DO $$ BEGIN
               ALTER TABLE "herd_tracking" ADD CONSTRAINT "herd_tracking_holder_contact_id_fkey"
                   FOREIGN KEY ("holder_contact_id") REFERENCES "buyer_contact" ("id") ON DELETE SET NULL;
           EXCEPTION WHEN duplicate_object THEN NULL;
           END $$;"""
    )
    DATABASE.execute_sql(
        'CREATE INDEX IF NOT EXISTS "herdtracking_holder_contact_id" ON "herd_tracking" ("holder_contact_id")'
    )
    DATABASE.execute_sql(
        'ALTER TABLE "herd_tracking" ADD COLUMN IF NOT EXISTS "buyer_removed" BOOLEAN NOT NULL DEFAULT false'
    )


def migrate_43_to_44():
    """ADR-0016: buyer_contact, the buyer outside the association, and holder_contact_id becomes its FK."""
    with DATABASE.atomic():
        _create_buyer_contact_guards()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=44, comment="buyer_contact; herd_tracking.holder_contact_id FK", applied=datetime.now()
        ).execute()


def migrate_44_to_45():
    """Issue #70: matrikel_audit rows written by the nightly anonymization have no user as actor."""
    with DATABASE.atomic():
        # DROP NOT NULL is idempotent; SQLite builds the table from the model, which already allows NULL.
        if not isinstance(DATABASE, SqliteDatabase) and "matrikel_audit" in DATABASE.get_tables():
            DATABASE.execute_sql('ALTER TABLE "matrikel_audit" ALTER COLUMN "actor_id" DROP NOT NULL')
        SchemaHistory.insert(  # pylint: disable=E1120
            version=45, comment="matrikel_audit.actor may be NULL", applied=datetime.now()
        ).execute()


_REX_MENTION = "rex"  # unanchored: "ickerex" and "dvärgrex" are candidates too, and fail the shape below
# Reads individual.hair_notes, color_note and (for the "normal" check only) notes; nothing else.
# A field that contains rex anywhere is clean only if it is colour words from a closed vocabulary followed by rex or
# rexpäls(ad|ade|en) as the last token, and it has none of the doubts below: carriers, negations, relatives,
# questions. A "normal" in hair_notes, color_note or notes blocks the row, and so does a hair_notes that is
# exactly an explicit no ("nej", "ej", "inga avvikelser", "inga", "-", "normal"), even when rex is only in
# color_note. Everything else is deliberately left rex = false for manual review. Those rows stay findable
# afterwards by a read-only query (rex false and the text mentions rex), so the migration logs counts only, never ids.
_REX_WORDS = (
    r"sv[aä]rt|sv[aä]rta|bl[åa]|bl[åa]tt|bl[åa]a|brun|bruna|brunt|gul|gula|gult|vit|vita|vitt|gr[åa]|gr[åa]tt|gr[åa]a"
    r"|r[öo]d|r[öo]da|r[öo]tt|tegel(r[öo]d)?|choklad(brun)?|japan|siames|agouti|havanna|madagaskar|orange|lila"
    r"|chinchilla|harlekin|tricolor|albino|hermelin|dalmatiner|vildf[äa]rgad|ja"
)
# Words are joined by whitespace, "/", "," or "."; a "-" only joins one colour word directly to rex.
_REX_SHAPE = r"^\s*((" + _REX_WORDS + r")[\s/,.]+)*((" + _REX_WORDS + r")-)?rex(-?päls(ad|ade|en)?)?[.\s]*$"
_REX_NO = r"^\s*(nej|ej|inga avvikelser|inga|-|normal)\s*$"
_REX_DOUBT = (
    r"b[äÄ]r",
    r"anlag",
    r"inslag",
    r"\msplit",
    r"\m(ej|inte|inget|ingen|icke|utan|nej|ev|kanske|negativ|testad|känt|efter|syskon|kullsyskon|far|mor|dotter|son)\M",
    r"f[öÖ]r[äÄ]ld",
    r"fader|moder",
    r"hane|hona",
    r"rex(fri|mor|far)",
    r"\?",
    r"mamma|pappa|bror|syster|mormor|farfar|morfar|moster|faster|avkomma|kull|syskon|dotter",
    r"eventuellt|troligen|m[öÖ]jligen|os[äÄ]ker|oklart|ok[äÄ]nt|\mkan\M|inga|aldrig|\mnot\M|\mnon\M",
    r"fri\M|fr[åÅ]n|tecken|halv|\x25|\mgen|linje|korsning|hetero|negativ|\mliknande",
    r"\m(far|mor)|sakna|\mno\M",
)


def _rex_sql(template, fields=("hair_notes", "color_note")):
    """One condition over the fields, each judged on its own: template with FIELD."""
    return " OR ".join(template.replace("FIELD", f"normalize(coalesce({f}, ''), NFC)") for f in fields)


_REX_MENTIONED = _rex_sql("FIELD ~* '" + _REX_MENTION + "'")
_REX_DOUBTFUL = (  # a field with rex in it that is not clean, a "normal" in any field, or an explicit no in hair_notes
    "("
    + _rex_sql(
        "(FIELD ~* '"
        + _REX_MENTION
        + "' AND (FIELD !~* '"
        + _REX_SHAPE
        + "' OR FIELD ~* '"
        + "|".join(_REX_DOUBT)
        + "'))"
    )
    + ") OR ("
    + _rex_sql("FIELD ~* 'normal'", ("hair_notes", "color_note", "notes"))
    + ") OR ("
    + _rex_sql("FIELD ~* '" + _REX_NO + "'", ("hair_notes",))
    + ")"
)


def migrate_45_to_46():
    """individual.rex: the coat, rex or normal. Rabbits whose notes say rex get true; the notes are not touched.
    The column is added in raw SQL (no audit rows); the UPDATE is audited, so the rows it set can be found.
    Only the run that creates the column sets rex from text; a replay must not undo later corrections."""
    with DATABASE.atomic():
        created = "rex" not in {c.name for c in DATABASE.get_columns("individual")}
        DATABASE.execute_sql("ALTER TABLE individual ADD COLUMN IF NOT EXISTS rex BOOLEAN NOT NULL DEFAULT false")
        if created:
            excluded = DATABASE.execute_sql(
                f"SELECT count(*) FROM individual WHERE ({_REX_MENTIONED}) AND ({_REX_DOUBTFUL})"
            ).fetchone()[0]
            done = DATABASE.execute_sql(
                f"UPDATE individual SET rex = true WHERE ({_REX_MENTIONED}) AND NOT ({_REX_DOUBTFUL})"
            ).rowcount
            note = f"set from free text on {done}, {excluded} excluded"
        else:
            note = "column existed, free text not read"
        logger.info(f"rex: {note}")
        SchemaHistory.insert(  # pylint: disable=E1120
            version=46,
            comment=f"individual.rex; {note}",
            applied=datetime.now(),
        ).execute()


def migrate_46_to_47():
    """A person's choice to show her name as "Intygas av" on the public certificate check page (stamboken #6),
    and the role a certificate was issued in (NULL on older rows). Accounts that exist now keep showing their name,
    as the check page did before (Jonas 2026-11-23), until they change it; a new account starts as not chosen (NULL)."""
    with DATABASE.atomic():
        if "name_on_check_page" not in {c.name for c in DATABASE.get_columns("hbuser")}:
            # The default fills the existing rows without firing the audit row trigger (no per-user audit copy);
            # dropping it leaves NULL for every account created afterwards.
            DATABASE.execute_sql("ALTER TABLE hbuser ADD COLUMN name_on_check_page BOOLEAN DEFAULT true")
            DATABASE.execute_sql("ALTER TABLE hbuser ALTER COLUMN name_on_check_page DROP DEFAULT")
            # Re-attach the audit triggers with name_on_check_page excluded from change detection (AUDITED_TABLES),
            # so the update below and every later change of only the choice write no audit row. Idempotent.
            _create_audit_table_and_triggers()
            # Accounts whose person was anonymised already: off, as anonymize_person sets it from now on. Only when
            # the column is new: a replay must not undo a choice made since.
            if "matrikel_audit" in DATABASE.get_tables():
                DATABASE.execute_sql(
                    "UPDATE hbuser SET name_on_check_page = false WHERE name_on_check_page AND user_id IN ("
                    " SELECT (payload->>'user_id')::int FROM matrikel_audit"
                    " WHERE action = 'person_user_unlinked' AND payload->>'source' = 'anonymize')"
                )
        if "digitalcertificatev2" in DATABASE.get_tables():
            DATABASE.execute_sql("ALTER TABLE digitalcertificatev2 ADD COLUMN IF NOT EXISTS issued_as VARCHAR(20)")
        SchemaHistory.insert(  # pylint: disable=E1120
            version=47,
            comment="hbuser.name_on_check_page, digitalcertificatev2.issued_as",
            applied=datetime.now(),
        ).execute()


def migrate_47_to_48():
    """One account per Google identity. Where two accounts hold one, creating the index fails: the schema stays at 47
    and the API does not start (nor the demo API on its copy). Count before deploying and fix the data while the old
    release still runs (README, "Sessions")."""
    with DATABASE.atomic():
        DATABASE.execute_sql(GOOGLE_IDENTITY_INDEX_SQL)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=48, comment="authenticators: unique Google identity", applied=datetime.now()
        ).execute()


def migrate_48_to_49():
    """One-time codes by mail, members' previous addresses and when a member's address starts to count for login.
    Not audited: the rows hold addresses, and both tables are purged."""
    with DATABASE.atomic():
        DATABASE.execute_sql("ALTER TABLE member ADD COLUMN IF NOT EXISTS email_login_from TIMESTAMPTZ")
        DATABASE.create_tables([LoginCode, MemberPreviousAddress], safe=True)
        SchemaHistory.insert(  # pylint: disable=E1120
            version=49, comment="login_code, member_previous_address, member.email_login_from", applied=datetime.now()
        ).execute()


def _add_herd_contact_member_fk():
    """herd.contact_member_id -> member, added once both tables exist (a deferred FK is not in CREATE TABLE).
    Safe on every init(): does nothing while the column or the member table is missing or the constraint exists."""
    DATABASE.execute_sql(
        """
        DO $$ BEGIN
            IF to_regclass('member') IS NOT NULL
               AND EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = current_schema() AND table_name = 'herd'
                             AND column_name = 'contact_member_id')
               AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'herd_contact_member_id_fkey'
                               AND conrelid = 'herd'::regclass) THEN
                ALTER TABLE herd ADD CONSTRAINT herd_contact_member_id_fkey
                    FOREIGN KEY (contact_member_id) REFERENCES member (member_id) ON DELETE SET NULL;
            END IF;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def _compare_linked_herds():
    """#117, Överflyttning: herds linked before the comparison existed are compared once (contact_pending NULL), if
    their membership is active; the others stay uncompared and read their own columns until it is.
    Version 50's columns only, read and written by name, so a replay works after later migrations add columns.
    membership and member are locked by the LOCKs and herd by the ALTER in migrate_49_to_50, so the register
    cannot change while the herds are compared."""
    from utils.herd_contact import compare_with_register  # pylint: disable=import-outside-toplevel

    # A household erased before the comparison existed: what on_household_erased does, since the nightly job
    # skips erased persons. Erased is matrikel.is_anonymized, the name pair anonymize_person writes.
    cleared = ", ".join(f'"{c}" = NULL, "{c}_privacy" = \'private\'' for c in HERD_CONTACT_COLUMNS)
    DATABASE.execute_sql(
        f"""UPDATE herd SET {cleared}, contact_member_id = NULL, contact_pending = '[]'
            WHERE membership_id IS NOT NULL AND contact_pending IS NULL
              AND EXISTS (SELECT 1 FROM member m WHERE m.membership_id = herd.membership_id)
              AND NOT EXISTS (SELECT 1 FROM member m WHERE m.membership_id = herd.membership_id
                              AND NOT (m.first_name = 'Borttagen' AND m.last_name = 'person'))"""
    )
    columns = ("name", "email", "mobile_phone", "physical_address")
    rows = Herd.select(
        Herd.id,
        Herd.membership,
        *(getattr(Herd, c) for c in columns),
        *(getattr(Herd, f"{c}_privacy") for c in columns),
    ).where(
        Herd.contact_pending.is_null(True),
        # a membership that is not active is compared when it becomes active (on_membership_active)
        Herd.membership.in_(Membership.select(Membership.id).where(Membership.membership_status == "active")),
    )
    for herd in rows:
        changes, _ = compare_with_register(herd, include_organization=False)
        Herd.update(**changes).where(Herd.id == herd.id, Herd.contact_pending.is_null(True)).execute()


def migrate_49_to_50():
    """#117: herd.contact_member and herd.contact_pending; herd contact values leave the audit history.
    The columns are added in raw SQL (no audit rows). The contact columns become snapshot_excluded, and the
    values already in audit_log are removed with the purge_user_audit_pii mechanism (rule lifted, same transaction).
    Then the herds already linked are compared with the register, with the new triggers in place."""
    with DATABASE.atomic():
        if not isinstance(DATABASE, SqliteDatabase):
            # membership first (order membership, member, herd). EXCLUSIVE waits for a transaction holding a
            # membership row FOR UPDATE: retire_membership then writes member and membership, which SHARE deadlocks
            DATABASE.execute_sql("LOCK TABLE membership IN EXCLUSIVE MODE")
            # Take member's lock first: ALTER herd then ADD FOREIGN KEY on member, in that order, could
            # deadlock with a matrikel import that inserts a member and then reads herd.
            DATABASE.execute_sql("LOCK TABLE member IN SHARE ROW EXCLUSIVE MODE")
        DATABASE.execute_sql('ALTER TABLE herd ADD COLUMN IF NOT EXISTS "contact_member_id" INTEGER')
        DATABASE.execute_sql('ALTER TABLE herd ADD COLUMN IF NOT EXISTS "contact_pending" JSONB')
        if not isinstance(DATABASE, SqliteDatabase):
            _add_herd_contact_member_fk()
            _create_audit_table_and_triggers()  # re-runnable; picks up the new snapshot_excluded list
            DATABASE.execute_sql("DROP RULE IF EXISTS audit_log_no_update ON audit_log")
            DATABASE.execute_sql(
                "UPDATE audit_log SET old_data = old_data - %s::text[], new_data = new_data - %s::text[]"
                " WHERE table_name = 'herd'",
                (list(HERD_CONTACT_COLUMNS), list(HERD_CONTACT_COLUMNS)),
            )
            DATABASE.execute_sql(AUDIT_LOG_NO_UPDATE_RULE)
            _compare_linked_herds()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=50,
            comment="herd.contact_member, herd.contact_pending; herd contact values out of audit_log",
            applied=datetime.now(),
        ).execute()


_REPORT_V2_COLUMNS = (
    ("status", "TEXT NOT NULL DEFAULT 'legacy'"),  # existing rows are the legacy reports
    ("source", "TEXT"),
    ("access_code_id", "INTEGER"),
    ("entered_by_id", 'INTEGER REFERENCES "hbuser" ("user_id")'),
    ("on_time_set_by_id", 'INTEGER REFERENCES "hbuser" ("user_id")'),
    ("support_approved_by_id", 'INTEGER REFERENCES "hbuser" ("user_id")'),
    ("voided_by_user_id", 'INTEGER REFERENCES "hbuser" ("user_id")'),
    ("inbox_item_id", "INTEGER"),
    ("received_at", "TIMESTAMPTZ"),
    ("support_approved_at", "TIMESTAMPTZ"),
    ("voided_at", "TIMESTAMPTZ"),
    ("on_time_override", "BOOLEAN"),
    ("revision", "INTEGER NOT NULL DEFAULT 0"),
    ("voided_by_access_code_id", "INTEGER"),
    ("void_reason", "TEXT"),
)
_LEGACY_REPORT_FIELDS = ("name", "publish", "publish_tel", "publish_email", "publish_address", "generated_by_id")
_ACCESS_CODE_COLUMNS = (
    ("yearlyherdreport", "access_code_id"),
    ("yearlyherdreport", "voided_by_access_code_id"),
    ("herd_tracking", "access_code_id"),
    ("herd_tracking", "voided_by_access_code_id"),
    ("individual_command", "access_code_id"),
)
# (table, column, DDL): what migration 51 adds to tables it does not create, grouped by table; the boot's repair
# adds the ones a database at 51 lacks (S5)
_ADDED_COLUMNS = (
    ("yearlyreportround", "deadline", "DATE"),
    ("publication_consent_change", "submission_id", "INTEGER"),  # Task 11
    ("breeding", "litter_size6w_preliminary", "BOOLEAN NOT NULL DEFAULT false"),
    ("inbox_item", "ref_data", "JSONB"),  # 4a Task 5: the purchase notice
    *(("yearlyherdreport", name, ddl) for name, ddl in _REPORT_V2_COLUMNS),
    ("herd_tracking", "access_code_id", "INTEGER"),
    ("herd_tracking", "voided_by_access_code_id", "INTEGER"),
    ("individual_command", "access_code_id", "INTEGER"),
)
ARSRAPPORT_51 = "yearly report v2:"  # how migration 51's schema_history comment starts
# A voided row has exactly one voider: the account or the report link. PostgreSQL keeps this text in
# pg_get_constraintdef, so the swap in _create_arsrapport_schema looks for it.
_HT_VOID_ACTOR = "(voided_by_user_id IS NULL) <> (voided_by_access_code_id IS NULL)"
_HT_VOID_CHECK = (
    "(voided_at IS NULL AND voided_by_user_id IS NULL AND voided_by_access_code_id IS NULL "
    "AND voided_operation_id IS NULL AND voided_reason IS NULL) OR (voided_at IS NOT NULL "
    f"AND ({_HT_VOID_ACTOR}) "
    "AND voided_operation_id IS NOT NULL AND btrim(coalesce(voided_reason, '')) <> '')"
)


def _create_arsrapport_schema():
    """
    Idempotent: the yearly report v2 tables, and what they add to yearlyreportround, yearlyherdreport, breeding,
    herd_tracking, individual_command and inbox_item, with the names a fresh bootstrap gives them (an FK is
    <table>_<column>_fkey). Called from init() and migrate_50_to_51. Skipped on SQLite.
    """
    if isinstance(DATABASE, SqliteDatabase):
        return
    DATABASE.create_tables(ARSRAPPORT_MODELS, safe=True)
    sql = DATABASE.execute_sql
    _add_columns(_ADDED_COLUMNS)
    sql(
        'ALTER TABLE "yearlyherdreport" '
        + ", ".join(f'ALTER COLUMN "{name}" DROP NOT NULL' for name in _LEGACY_REPORT_FIELDS)
    )
    YearlyHerdReport._schema.create_indexes(safe=True)  # the new FK indexes, named as on a fresh bootstrap
    sql('ALTER TABLE "individual_command" ALTER COLUMN "actor_id" DROP NOT NULL')
    constraints = (
        ("yearlyherdreport", "yearlyherdreport_status_check", f"CHECK ({_sql_in('status', REPORT_STATUSES)})"),
        ("yearlyherdreport", "yearlyherdreport_source_check", f"CHECK ({_sql_in('source', REPORT_SOURCES)})"),
        (
            "yearlyherdreport",
            "yearlyherdreport_void_check",
            "CHECK ((status = 'voided') = (voided_at IS NOT NULL) AND (voided_at IS NULL "
            "OR voided_by_user_id IS NOT NULL OR voided_by_access_code_id IS NOT NULL))",
        ),
        (
            "individual_command",
            "individual_command_actor_check",
            "CHECK ((actor_id IS NULL) <> (access_code_id IS NULL))",
        ),
        *(
            (table, f"{table}_{column}_fkey", f'FOREIGN KEY ("{column}") REFERENCES "report_access_code" ("id")')
            for table, column in _ACCESS_CODE_COLUMNS
        ),
    )
    for table, name, definition in constraints:
        sql(
            f"""DO $$ BEGIN
                    ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition};
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;"""
        )
    # Replace, once, the CHECK that _create_herd_tracking_guards adds (migration 30 runs before the column exists),
    # and the "user or code" version this branch's yearly report migration first had.
    sql(
        f"""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint
                                WHERE conrelid = '"herd_tracking"'::regclass
                                  AND conname = 'herd_tracking_void_fields_check'
                                  AND strpos(pg_get_constraintdef(oid), '{_HT_VOID_ACTOR}') > 0) THEN
                    ALTER TABLE "herd_tracking" DROP CONSTRAINT IF EXISTS "herd_tracking_void_fields_check";
                    ALTER TABLE "herd_tracking" ADD CONSTRAINT "herd_tracking_void_fields_check"
                        CHECK ({_HT_VOID_CHECK});
                END IF;
            END $$;"""
    )
    sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_yearlyherdreport_submitted" ON "yearlyherdreport" (herd_id, round_id) '
        "WHERE status = 'submitted'"
    )
    sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_report_access_code_active" ON "report_access_code" (herd_id, round_id) '
        "WHERE revoked_at IS NULL"
    )
    sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_sale_proposal_open" ON "sale_proposal" (individual_id, report_id) '
        "WHERE state = 'foreslagen'"
    )


def _add_columns(columns):
    """ADD COLUMN IF NOT EXISTS for each (table, column, DDL) of `columns`, one ALTER TABLE per table."""
    for table, group in groupby(columns, key=lambda column: column[0]):
        DATABASE.execute_sql(
            f'ALTER TABLE "{table}" ' + ", ".join(f'ADD COLUMN IF NOT EXISTS "{name}" {ddl}' for _, name, ddl in group)
        )


def migrate_50_to_51():
    """Yearly report v2: rounds per genebank, the report row's status and actors, and the tables around it."""
    with DATABASE.atomic():
        _create_arsrapport_schema()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=51,
            comment=f"{ARSRAPPORT_51} rounds per genebank, submissions, drafts, sale proposals, access codes, "
            "change requests, consent history",
            applied=datetime.now(),
        ).execute()


ORGANIZATION_52 = "membership.organization_name and organization_number"  # migration 52's schema_history comment


def migrate_51_to_52():
    """Optional legal entity on a membership. Existing memberships keep NULL for both fields."""
    with DATABASE.atomic():
        existing = {c.name for c in DATABASE.get_columns("membership")}
        for field in (Membership.organization_name, Membership.organization_number):
            if field.name not in existing:
                migrate(DATABASE_MIGRATOR.add_column("membership", field.name, field))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=52, comment=ORGANIZATION_52, applied=datetime.now()
        ).on_conflict_ignore().execute()


def _create_buyer_invitations():
    BuyerInvitation.create_table(safe=True)
    DATABASE.execute_sql(
        """
        INSERT INTO mail_buyer_invitation (email_hash, created_at)
        SELECT coalesce(m.address_hash, b.erased_email_hash), max(m.created_at)
        FROM mail_message m LEFT JOIN buyer_contact b ON b.id = m.recipient_id
        WHERE m.kind = 'kopare.medlemskap' AND m.recipient_kind = 'buyer_contact'
          AND m.status IN ('sent', 'bounced') AND coalesce(m.address_hash, b.erased_email_hash) IS NOT NULL
        GROUP BY coalesce(m.address_hash, b.erased_email_hash)
        ON CONFLICT DO NOTHING
        """
    )


def _add_buyer_email_review():
    DATABASE.execute_sql(
        "ALTER TABLE buyer_contact ADD COLUMN IF NOT EXISTS email_review_pending BOOLEAN NOT NULL DEFAULT false"
    )


def migrate_52_to_53():
    """A notice can point at a rabbit instead of an intake item (a buyer erased their own data)."""
    with DATABASE.atomic():
        DATABASE.execute_sql(
            "ALTER TABLE notice ADD COLUMN IF NOT EXISTS individual_id INTEGER "
            "REFERENCES individual (individual_id) ON DELETE CASCADE"
        )
        DATABASE.execute_sql("ALTER TABLE buyer_contact ADD COLUMN IF NOT EXISTS erased_email_hash TEXT")
        _add_buyer_email_review()
        _create_buyer_invitations()
        # The index a fresh bootstrap gives the foreign key: the cascade looks the notices up by rabbit.
        DATABASE.execute_sql("CREATE INDEX IF NOT EXISTS notice_individual_id ON notice (individual_id)")
        SchemaHistory.insert(  # pylint: disable=E1120
            version=53, comment="notice.individual, buyer_contact.erased_email_hash", applied=datetime.now()
        ).execute()


def _lock_account_rules_snapshots():
    if isinstance(DATABASE, SqliteDatabase):
        return
    for action in ("UPDATE", "DELETE"):
        DATABASE.execute_sql(
            f"CREATE OR REPLACE RULE account_rules_no_{action.lower()} AS ON {action} TO account_rules_snapshot "
            "DO INSTEAD NOTHING"
        )


def migrate_53_to_54():
    """Record the published rules accepted by self-registered accounts."""
    with DATABASE.atomic():
        DATABASE.create_tables([AccountRulesSnapshot], safe=True)
        _lock_account_rules_snapshots()
        DATABASE.execute_sql(
            "ALTER TABLE hbuser ADD COLUMN IF NOT EXISTS rules_sha256 TEXT REFERENCES account_rules_snapshot(sha256)"
        )
        DATABASE.execute_sql("ALTER TABLE hbuser ADD COLUMN IF NOT EXISTS rules_accepted_at TIMESTAMPTZ")
        DATABASE.execute_sql("ALTER TABLE hbuser ADD COLUMN IF NOT EXISTS rules_version TEXT")
        DATABASE.execute_sql("ALTER TABLE mail_sender ADD COLUMN IF NOT EXISTS code_queue_errors TIMESTAMPTZ[]")
        DATABASE.execute_sql("ALTER TABLE mail_sender ADD COLUMN IF NOT EXISTS code_limit_at TIMESTAMPTZ")
        SchemaHistory.insert(  # pylint: disable=E1120
            version=54, comment="hbuser account rules acceptance", applied=datetime.now()
        ).execute()


def migrate_54_to_55():
    """History rows store each year's realised Ne, its standard error and the animals behind it.

    The trend drew a rolling ln(1 - F) regression instead.
    """
    with DATABASE.atomic():
        table = GeneticMetricsHistory._meta.table_name
        existing = {c.name for c in DATABASE.get_columns(table)}
        # A replay from below 16 creates the table from the current model, columns included.
        for name, fld in (
            ("effective_population_size", FloatField(null=True)),
            ("ne_se", FloatField(null=True)),
            ("ne_n", IntegerField(null=True)),
        ):
            if name not in existing:
                migrate(DATABASE_MIGRATOR.add_column(table, name, fld))
        SchemaHistory.insert(  # pylint: disable=E1120
            version=55, comment="history: realised Ne per report year", applied=datetime.now()
        ).execute()


def _create_field_indexes(model, *names):
    """
    The model's indexes on these fields only, named as a fresh bootstrap names them. All of the model's indexes
    would include ones on columns a later migration adds, which do not exist yet on an older database.
    """
    for index in model._meta.fields_to_index():
        if {getattr(field, "name", None) for field in index._expressions} <= set(names):
            DATABASE.execute(model._schema._create_index(index, safe=True))


def migrate_55_to_56():
    """A paper certificate's copy records whether its handler found it in agreement with the registry."""
    with DATABASE.atomic():
        DATABASE.execute_sql("ALTER TABLE inbox_document ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ")
        DATABASE.execute_sql(
            "ALTER TABLE inbox_document ADD COLUMN IF NOT EXISTS verified_by_id INTEGER "
            'REFERENCES "hbuser" ("user_id") ON DELETE SET NULL'
        )
        # NULL for a certificate saved before: the number it was saved as is not recorded, and its rabbit's may
        # have changed since, so such a copy is never marked checked.
        DATABASE.execute_sql("ALTER TABLE inbox_document ADD COLUMN IF NOT EXISTS saved_certificate TEXT")
        DATABASE.execute_sql("ALTER TABLE inbox_document ADD COLUMN IF NOT EXISTS saved_number TEXT")
        _create_field_indexes(InboxDocument, "verified_by")
        SchemaHistory.insert(  # pylint: disable=E1120
            version=56, comment="inbox_document: copy checked against the registry", applied=datetime.now()
        ).execute()


def migrate_56_to_57():
    """#273: a buyer's e-mail without a yes, kept only for the notice, for a sale without a försäljningsbevis."""
    with DATABASE.atomic():
        DATABASE.execute_sql(
            "ALTER TABLE buyer_contact ADD COLUMN IF NOT EXISTS email_notice_only BOOLEAN NOT NULL DEFAULT false"
        )
        for name, check in (
            ("buyer_contact_email_phone_need_consent", BUYER_EMAIL_PHONE_CHECK),
            ("buyer_contact_notice_only_no_consent", BUYER_NOTICE_ONLY_CHECK),
        ):
            DATABASE.execute_sql(f'ALTER TABLE buyer_contact DROP CONSTRAINT IF EXISTS "{name}"')
            DATABASE.execute_sql(f"ALTER TABLE buyer_contact ADD {check}")
        SchemaHistory.insert(  # pylint: disable=E1120
            version=57, comment="buyer_contact.email_notice_only", applied=datetime.now()
        ).execute()


SUPPORT_ACCOUNT_58 = "membership support account"  # migration 58's schema_history comment


def _create_support_account_guards():
    """Migration 58's CHECKs, from init() too: a known account type, and the herd's old account columns empty."""
    if isinstance(DATABASE, SqliteDatabase):
        return
    types = ", ".join(f"'{kind}'" for kind in ACCOUNT_TYPES)
    for name, table, expression in (
        ("ck_membership_bank_account_type", "membership", f"bank_account_type IN ({types})"),
        ("ck_herd_no_bank_account", "herd", "bank_account_number IS NULL AND bank_name IS NULL"),
    ):
        if not DATABASE.execute_sql("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,)).fetchone():
            DATABASE.execute_sql(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({expression})')


def _move_support_accounts():
    """
    Migration 58's move, every herd included, active or not: each membership takes the account its herds hold, and
    keeps one it holds already. A text that is only whitespace (tabs, newlines and no-break spaces too) is no value.
    Herds agree only on the same number and bank together, compared without whitespace and the marks . , - and
    ignoring case; letters such as BG or PG stay, so they keep two accounts apart. Nothing is merged or guessed: a
    membership whose herds (or its own account) differ, or an account on a herd without a membership, stops the
    migration before it writes, naming only ids and counts. A household whose persons are all anonymised gets no
    account (U14); its herds are emptied like the others.
    """

    def key(number, name):
        number, name = (number or "").strip(), (name or "").strip()
        return re.sub(r"[\s.,\-]", "", number).casefold(), " ".join(name.casefold().split()), bool(number or name)

    rows = DATABASE.execute_sql(
        "SELECT herd_id, membership_id, bank_account_number, bank_name FROM herd"
        " WHERE bank_account_number IS NOT NULL OR bank_name IS NOT NULL ORDER BY herd_id"
    ).fetchall()
    rows = [row for row in rows if key(*row[2:])[2]]
    orphans = [herd_id for herd_id, membership_id, *_ in rows if membership_id is None]
    held = {}
    for _, membership_id, number, name in (row for row in rows if row[1] is not None):
        held.setdefault(membership_id, []).append((number, name))
    # the names anonymize_person writes (utils.matrikel.ANONYMIZED_FIRST_NAME and _LAST_NAME)
    erased = {
        row[0]
        for row in DATABASE.execute_sql(
            "SELECT membership_id FROM member WHERE membership_id = ANY(%s) GROUP BY membership_id"
            " HAVING bool_and(first_name = 'Borttagen' AND last_name = 'person')",
            (list(held),),
        )
    }
    stored = DATABASE.execute_sql(
        "SELECT membership_id, bank_account_number, bank_name FROM membership WHERE membership_id = ANY(%s)",
        (list(held),),
    ).fetchall()
    moves, conflicts = {}, []
    for membership_id, *own in stored:
        if membership_id in erased:
            continue
        accounts = held[membership_id] + ([tuple(own)] if key(*own)[2] else [])
        if len({key(*account) for account in accounts}) > 1:
            conflicts.append(membership_id)
        elif not key(*own)[2]:
            moves[membership_id] = [(value or "").strip() or None for value in accounts[0]]
    if conflicts or orphans:
        conflicts = sorted(conflicts)
        raise RuntimeError(
            "Migration 58 stopped, nothing moved: correct the support accounts first. "
            f"{len(conflicts)} memberships whose herds hold different accounts (membership_id {conflicts}); "
            f"{len(orphans)} herds with an account but no membership (herd_id {orphans})."
        )
    for membership_id, (number, name) in moves.items():
        Membership.update(bank_account_number=number, bank_name=name).where(Membership.id == membership_id).execute()
    # The trigger would copy every account into new audit rows (migration 40's guard); the herds are emptied unlogged.
    DATABASE.execute_sql('ALTER TABLE "herd" DISABLE TRIGGER "audit_trigger"')
    DATABASE.execute_sql(
        "UPDATE herd SET bank_account_number = NULL, bank_name = NULL"
        " WHERE bank_account_number IS NOT NULL OR bank_name IS NOT NULL"
    )
    DATABASE.execute_sql('ALTER TABLE "herd" ENABLE TRIGGER "audit_trigger"')


def migrate_57_to_58():
    """
    The support account moves from the herd to its membership, with a type (bankkonto, bankgiro or plusgiro; Jonas
    2026-11-18), so that a member with two herds has one account. The herd's columns stay, empty under a CHECK.
    """
    with DATABASE.atomic():
        if not isinstance(DATABASE, SqliteDatabase):
            # membership before herd, the matrikel's order (lock_herd); the move reads both and nothing may write them
            DATABASE.execute_sql("LOCK TABLE membership, herd IN ACCESS EXCLUSIVE MODE")
        existing = {c.name for c in DATABASE.get_columns("membership")}
        for field in (Membership.bank_account_type, Membership.bank_account_number, Membership.bank_name):
            if field.name not in existing:
                migrate(DATABASE_MIGRATOR.add_column("membership", field.name, field))
        if not isinstance(DATABASE, SqliteDatabase):
            _move_support_accounts()
            _create_support_account_guards()
        SchemaHistory.insert(  # pylint: disable=E1120
            version=58, comment=SUPPORT_ACCOUNT_58, applied=datetime.now()
        ).execute()


def migrate_21_to_22():
    """Add litter_number to Breeding table and backfill from minted numbers."""
    with DATABASE.atomic():
        if "breeding" not in DATABASE.get_tables():
            SchemaHistory.insert(
                version=22,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return

        cols = [x.name for x in DATABASE.get_columns("breeding")]

        if "litter_number" not in cols:
            migrate(DATABASE_MIGRATOR.add_column("breeding", "litter_number", SmallIntegerField(null=True)))

        # The index may already exist while schema_history says < 22: a
        # data-only demo sync restores old rows into an already-migrated
        # schema, so the replay reruns here with the unique index live and
        # the backfill UPDATEs below crash on transient collisions that the
        # dedupe pass would clear. Drop it and recreate at the end (same
        # transaction), making the migration self-contained.
        DATABASE.execute_sql('DROP INDEX IF EXISTS "idx_breeding_herd_year_litter"')

        # Backfill litters that already have minted individuals from the number
        # itself ({herd}-{YY}{L}{slot} → L) — the only source that cannot
        # disagree with what was actually issued. MODE() picks the most common
        # parse when siblings disagree.
        DATABASE.execute_sql(r"""
            UPDATE breeding SET litter_number = sub.lit
            FROM (
                SELECT i.breeding_id,
                       MODE() WITHIN GROUP (
                           ORDER BY ((regexp_match(i.number, '-\d\d(\d+)\d$'))[1])::int
                       ) AS lit
                FROM individual i
                WHERE i.breeding_id IS NOT NULL
                GROUP BY i.breeding_id
            ) sub
            WHERE breeding.breeding_id = sub.breeding_id
              AND breeding.litter_number IS NULL
              AND sub.lit BETWEEN 1 AND 32767
        """)

        # Empty litters: chronological rank per herd/year. Legacy minting
        # bucketed by year(COALESCE(birth_date, breed_date)) — no +30 days —
        # so the rank partition must match it.
        DATABASE.execute_sql("""
            UPDATE breeding SET litter_number = sub.rn
            FROM (
                SELECT breeding_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY breeding_herd_id,
                                        EXTRACT(YEAR FROM COALESCE(birth_date, breed_date))
                           ORDER BY COALESCE(birth_date, breed_date + INTERVAL '30 days'),
                                    breeding_id
                       ) AS rn
                FROM breeding
                WHERE birth_date IS NOT NULL OR breed_date IS NOT NULL
            ) sub
            WHERE breeding.breeding_id = sub.breeding_id
              AND breeding.litter_number IS NULL
        """)

        # The unique index buckets by year(COALESCE(birth_date, breed_date + 30
        # days)); clear any backfill duplicates within a bucket (keeping litters
        # with minted individuals, then lowest id) so the index can always be
        # created. Cleared rows stay NULL until assigned via birth registration
        # or renumbering.
        cursor = DATABASE.execute_sql("""
            WITH ranked AS (
                SELECT b.breeding_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY b.breeding_herd_id,
                                        EXTRACT(YEAR FROM COALESCE(b.birth_date, b.breed_date + INTERVAL '30 days')),
                                        b.litter_number
                           ORDER BY (ic.breeding_id IS NULL), b.breeding_id
                       ) AS rn
                FROM breeding b
                LEFT JOIN (
                    SELECT DISTINCT breeding_id FROM individual WHERE breeding_id IS NOT NULL
                ) ic ON ic.breeding_id = b.breeding_id
                WHERE b.litter_number IS NOT NULL
            )
            UPDATE breeding SET litter_number = NULL
            WHERE breeding_id IN (SELECT breeding_id FROM ranked WHERE rn > 1)
        """)
        if cursor.rowcount:
            logger.warning(
                "litter_number backfill: cleared %s duplicate(s) within a herd/year; assign manually via renumbering",
                cursor.rowcount,
            )

        _create_breeding_litter_number_index()

        SchemaHistory.insert(
            version=22,
            comment="Add litter_number to breeding with backfill and unique index",
            applied=datetime.now(),
        ).execute()


def migrate_22_to_23():
    """Add bunny roster table + Individual.voided; audit the bunny table."""
    with DATABASE.atomic():
        if "individual" not in DATABASE.get_tables():
            SchemaHistory.insert(
                version=23,
                comment="not yet bootstrapped, skipping",
                applied=datetime.now(),
            ).execute()
            return
        DATABASE.create_tables([Bunny], safe=True)  # idempotent (CREATE TABLE IF NOT EXISTS); emits the Meta.Check
        # Guard the column adds so the migration is idempotent on a model-bootstrapped DB:
        # init()/replay create `individual` from the current model, which already carries these
        # columns, so an unconditional ALTER ADD would raise "column already exists". Mirrors the
        # litter_number guard in migrate_21_to_22.
        ind_cols = [c.name for c in DATABASE.get_columns("individual")]
        ops = []
        if "voided" not in ind_cols:
            ops.append(DATABASE_MIGRATOR.add_column("individual", "voided", BooleanField(default=False)))
        if "voided_at" not in ind_cols:
            ops.append(DATABASE_MIGRATOR.add_column("individual", "voided_at", DateTimeField(null=True)))
        if ops:
            # peewee's add_column backfills the default with an UPDATE over all
            # rows, which would write a "voided: null → false" audit entry for
            # every individual. Suppress the trigger during the backfill; the
            # DISABLE rolls back with the transaction if the migration fails.
            suppress_audit = not isinstance(DATABASE, SqliteDatabase)
            if suppress_audit:
                DATABASE.execute_sql("ALTER TABLE individual DISABLE TRIGGER USER")
            migrate(*ops)
            if suppress_audit:
                DATABASE.execute_sql("ALTER TABLE individual ENABLE TRIGGER USER")
        _create_audit_table_and_triggers()  # idempotent, loops AUDITED_TABLES → attaches bunny trigger
        SchemaHistory.insert(
            version=23,
            comment="bunny roster + Individual.voided",
            applied=datetime.now(),
        ).execute()


def _create_member_indexes():
    """Indexes for member + member_application (raw SQL — partial/expression
    indexes Peewee can't declare).

    Called from BOTH migrate_23_to_24() and init(): fresh databases are
    bootstrapped via init() without running migrations (same reason
    init() calls _create_audit_table_and_triggers()). All statements are
    IF NOT EXISTS — safe to call repeatedly.

    v2 contract note: the per-gene-bank email index, the genebank scope
    indexes and the name+address index referenced columns dropped by
    migrate_26_to_27 — they were removed from here so a from-empty
    bootstrap never references dropped columns.
    """
    # Global unique partial on workspace_email — Workspace-issued
    # addresses are globally unique by Google's constraint; we mirror
    # that so two Member rows can't claim the same workspace login.
    DATABASE.execute_sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_member_workspace_email_unique" '
        'ON "member" (LOWER("workspace_email")) '
        'WHERE "workspace_email" IS NOT NULL'
    )

    # One user ↔ at most one person row (Phase 19). Replaces the
    # non-unique auto-link lookup index; partial so unlinked rows stay free.
    # Index ONLY — init() runs at every API start and must never rewrite data;
    # the duplicate-link preflight lives in
    # _apply_phase19_schema_changes() (migration path). A pre-v29 database
    # always migrates before init() (prestart_migrations.py + the module-level
    # check_migrations() run first), so CREATE UNIQUE INDEX never meets legacy
    # duplicates here.
    DATABASE.execute_sql('DROP INDEX IF EXISTS "idx_member_user"')
    DATABASE.execute_sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_member_user_unique" ON "member" ("user_id") WHERE "user_id" IS NOT NULL'
    )

    # Non-unique email lookup for manager tooling (reapply tracking,
    # spam patterns etc). Email is NOT unique on applications since
    # a rejected applicant may reapply.
    DATABASE.execute_sql(
        'CREATE INDEX IF NOT EXISTS "idx_member_application_email" ON "member_application" (LOWER("email"))'
    )


def _create_matrikel_indexes():
    """Partial unique indexes + CHECK constraints for the v2 matrikel tables
    (raw SQL — peewee Meta.indexes can't express WHERE, and ALTER TABLE ...
    ADD CONSTRAINT has no IF NOT EXISTS).

    Called from BOTH migrate_25_to_26() and init(): fresh databases are
    bootstrapped via init() without running migrations. Idempotent — safe
    to call repeatedly.
    """
    # Unique member number where set (friexemplar memberships have NULL).
    DATABASE.execute_sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_membership_member_number_unique" '
        'ON "membership" ("member_number") WHERE "member_number" IS NOT NULL'
    )

    # At most one ACTIVE main member per membership. The minimum-one side
    # is enforced in the API layer (utils/matrikel.py).
    DATABASE.execute_sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "idx_member_single_active_main" '
        'ON "member" ("membership_id") '
        'WHERE "role" = \'huvudmedlem\' AND "end_date" IS NULL'
    )

    # Lookup paths: persons of a membership, herds of a membership.
    DATABASE.execute_sql('CREATE INDEX IF NOT EXISTS "idx_member_membership" ON "member" ("membership_id")')
    DATABASE.execute_sql('CREATE INDEX IF NOT EXISTS "idx_herd_membership" ON "herd" ("membership_id")')

    # CHECK constraints are PostgreSQL-only: SQLite can't ALTER TABLE ADD
    # CONSTRAINT (same guard as _create_audit_table_and_triggers).
    if isinstance(DATABASE, SqliteDatabase):
        return
    checks = [
        (
            "ck_membership_status",
            "membership",
            "membership_status IN ('active', 'inactive', 'pending', 'friexemplar')",
        ),
        # NULL passes a CHECK (SQL three-valued logic) — friexemplar rows OK.
        ("ck_membership_member_number_positive", "membership", "member_number > 0"),
        ("ck_member_role", "member", "role IN ('huvudmedlem', 'familjemedlem', 'skotare')"),
    ]
    for name, table, expression in checks:
        exists = DATABASE.execute_sql("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,)).fetchone()
        if not exists:
            DATABASE.execute_sql(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({expression})')


def _seed_member_number_counter():
    """Seed the single-row member-number high-water mark. Idempotent: no-op
    when a row exists.

    Mark = max of existing membership.member_number and the numeric
    suffixes of herd codes matching ^[GM](digits)$ across BOTH gene banks —
    a new member must never get a number whose G/M herd already belongs to
    someone else. Herd codes that do not
    match the pattern are logged for human review.

    Called from BOTH migrate_25_to_26() and init().
    """
    if MemberNumberCounter.select().count() > 0:
        return

    mark = Membership.select(fn.MAX(Membership.member_number)).scalar() or 0
    herd_code = re.compile(r"^[GM](\d+)$")
    for herd in Herd.select(Herd.herd):
        match = herd_code.match(herd.herd or "")
        if match:
            mark = max(mark, int(match.group(1)))
        else:
            logger.warning(
                "member-number counter seed: herd code %r does not match ^[GM](digits)$ — ignored",
                herd.herd,
            )
    MemberNumberCounter.insert(value=mark).execute()
    logger.info("member-number counter seeded at %s", mark)


def migrate_23_to_24():
    """Add the member-registry tables for Phase 8 — edited in place for
    Member Model v2 (legal: never ran outside dev/demo). Creates the v2
    table set so a from-empty replay walks straight to the v2 shape
    """
    with DATABASE.atomic():
        DATABASE.create_tables(
            [Membership, MemberNumberCounter, Member, MemberApplication, HerdAccessGrant, MatrikelAudit]
        )
        _create_member_indexes()

        SchemaHistory.insert(  # pylint: disable=E1120
            version=24,
            comment="Add member registry tables (Phase 8, v2 table set)",
            applied=datetime.now(),
        ).execute()


def migrate_24_to_25():
    """Allow NULL MemberApplication.genebank (assigned at approval instead)."""
    with DATABASE.atomic():
        # Guard: after the v2 contract migration (26→27) drops the column,
        # a from-empty replay reaches this step with no genebank_id at all.
        cols = [x.name for x in DATABASE.get_columns("member_application")]
        if "genebank_id" in cols:
            DATABASE.execute_sql("ALTER TABLE member_application ALTER COLUMN genebank_id DROP NOT NULL")

        SchemaHistory.insert(  # pylint: disable=E1120
            version=25,
            comment="Make member_application.genebank_id nullable (assigned at approval)",
            applied=datetime.now(),
        ).execute()


def migrate_25_to_26():
    """Member Model v2 expand migration: membership/person
    split, herd ownership FK, grants, audit log, member-number counter.

    Written defensively (existence guards): on a from-empty replay the v2
    shape already exists (init() or the edited migrate_23_to_24 created it)
    and every step is a no-op walk-through. On a real v25 dev/demo database
    it performs the full expand. Superseded columns are dropped by the
    contract migration (26→27), not here.
    """
    with DATABASE.atomic():
        # 1. New tables (CREATE TABLE IF NOT EXISTS via peewee safe=True).
        DATABASE.create_tables([Membership, MemberNumberCounter, HerdAccessGrant, MatrikelAudit])

        # 2. New columns on member + herd (guarded ADD COLUMN).
        member_cols = [x.name for x in DATABASE.get_columns("member")]
        if "membership_id" not in member_cols:
            DATABASE.execute_sql(
                'ALTER TABLE "member" ADD COLUMN "membership_id" INTEGER REFERENCES "membership" ("membership_id")'
            )
        if "role" not in member_cols:
            DATABASE.execute_sql('ALTER TABLE "member" ADD COLUMN "role" VARCHAR(20) NOT NULL DEFAULT \'huvudmedlem\'')
        if "end_date" not in member_cols:
            DATABASE.execute_sql('ALTER TABLE "member" ADD COLUMN "end_date" DATE')
        herd_cols = [x.name for x in DATABASE.get_columns("herd")]
        if "membership_id" not in herd_cols:
            DATABASE.execute_sql(
                'ALTER TABLE "herd" ADD COLUMN "membership_id" INTEGER REFERENCES "membership" ("membership_id")'
            )

        # 2b. Relax member.genebank_id NOW, not in a later task: approval
        # creates association-level person rows with no gene bank,
        # and a migration must never be edited after persistent databases
        # have executed it. Guarded on column existence so the from-empty
        # replay after the contract migration (column dropped) skips it;
        # DROP NOT NULL is idempotent on an already-nullable column.
        if "genebank_id" in member_cols:
            DATABASE.execute_sql('ALTER TABLE "member" ALTER COLUMN "genebank_id" DROP NOT NULL')

        # 3. Backfill — only on a real v25 database (the superseded columns
        # exist there; after the 26→27 contract they are gone and a replay
        # skips this). Raw SQL on purpose: the ORM stops mapping the old
        # columns after the contract migration.
        if "membership_status" in member_cols:
            rows = DATABASE.execute_sql(
                "SELECT member_id, membership_status, address, publication_consent, joined_date "
                'FROM "member" WHERE "membership_id" IS NULL'
            ).fetchall()
            for member_id, status, address, consent, joined in rows:
                cursor = DATABASE.execute_sql(
                    'INSERT INTO "membership" (membership_status, address, publication_consent, '
                    "joined_date, created_at, updated_at) "
                    "VALUES (%s, %s, CAST(%s AS jsonb), %s, now(), now()) RETURNING membership_id",
                    (status, address, json.dumps(consent if consent is not None else {}), joined),
                )
                membership_id = cursor.fetchone()[0]
                DATABASE.execute_sql(
                    'UPDATE "member" SET "membership_id" = %s, "role" = %s WHERE "member_id" = %s',
                    (membership_id, "huvudmedlem", member_id),
                )

            # 4. herd.membership from the old member.herd FK: exactly one
            # referencing member links the herd; several (the old FK was
            # unconstrained) → oldest row wins + warning for manual review.
            herd_refs = DATABASE.execute_sql(
                'SELECT herd_id, COUNT(*) FROM "member" WHERE "herd_id" IS NOT NULL GROUP BY herd_id'
            ).fetchall()
            for herd_id, ref_count in herd_refs:
                if ref_count > 1:
                    logger.warning(
                        "migrate_25_to_26: herd %s referenced by %s member rows — linking the oldest row",
                        herd_id,
                        ref_count,
                    )
                DATABASE.execute_sql(
                    'UPDATE "herd" SET "membership_id" = ('
                    'SELECT "membership_id" FROM "member" WHERE "herd_id" = %s '
                    'ORDER BY "created_at", "member_id" LIMIT 1) '
                    'WHERE "herd_id" = %s AND "membership_id" IS NULL',
                    (herd_id, herd_id),
                )

        # 5. Partial unique indexes + CHECKs, then seed the counter.
        _create_matrikel_indexes()
        _seed_member_number_counter()

        SchemaHistory.insert(  # pylint: disable=E1120
            version=26,
            comment="Member Model v2 expand: membership/person split, grants, audit, number counter",
            applied=datetime.now(),
        ).execute()


def migrate_26_to_27():
    """Member Model v2 contract migration: drop the superseded member
    columns and member_application.genebank, enforce member.membership_id
    NOT NULL.

    Guarded/IF EXISTS throughout: on a from-empty replay the columns and
    indexes never existed (migrate_23_to_24 creates the final v2 shape)
    and every statement is a no-op walk-through.

    Destructive: validates the 25→26 backfill invariant BEFORE dropping
    anything. A member row with NULL membership_id means the columns
    about to be dropped hold that row's only association/contact data —
    raising here rolls back the transaction, leaves the database at v26
    and blocks startup until the rows are backfilled. Never drop first and warn after.
    """
    with DATABASE.atomic():
        # Invariant gate — must come before any destructive DDL.
        null_count = DATABASE.execute_sql('SELECT COUNT(*) FROM "member" WHERE "membership_id" IS NULL').fetchone()[0]
        if null_count:
            raise RuntimeError(
                f"migrate_26_to_27: {null_count} member rows have NULL membership_id — "
                "the 25→26 backfill did not cover them; backfill manually before this "
                "contract migration can run (their genebank/address/status data would "
                "otherwise be destroyed)"
            )

        # Indexes on columns dropped below. Postgres would drop them with
        # the column; explicit drops also cover an index-only residue.
        DATABASE.execute_sql('DROP INDEX IF EXISTS "idx_member_genebank_email_unique"')
        DATABASE.execute_sql('DROP INDEX IF EXISTS "idx_member_genebank"')
        DATABASE.execute_sql('DROP INDEX IF EXISTS "idx_member_name_address"')
        DATABASE.execute_sql('DROP INDEX IF EXISTS "idx_member_application_status_genebank"')

        for column in ("genebank_id", "herd_id", "membership_status", "address", "publication_consent", "joined_date"):
            DATABASE.execute_sql(f'ALTER TABLE "member" DROP COLUMN IF EXISTS "{column}"')
        DATABASE.execute_sql('ALTER TABLE "member_application" DROP COLUMN IF EXISTS "genebank_id"')

        DATABASE.execute_sql('ALTER TABLE "member" ALTER COLUMN "membership_id" SET NOT NULL')

        SchemaHistory.insert(  # pylint: disable=E1120
            version=27,
            comment="Member Model v2 contract: drop superseded member columns",
            applied=datetime.now(),
        ).execute()


MIGRATIONS = {
    (None, 1): migrate_none_to_1,
    (1, 2): migrate_1_to_2,
    (2, 3): migrate_2_to_3,
    (3, 4): migrate_3_to_4,
    (4, 5): migrate_4_to_5,
    (5, 6): migrate_5_to_6,
    (6, 7): migrate_6_to_7,
    (7, 8): migrate_7_to_8,
    (8, 9): migrate_8_to_9,
    (9, 10): migrate_9_to_10,
    (10, 11): migrate_10_to_11,
    (11, 12): migrate_11_to_12,
    (12, 13): migrate_12_to_13,
    (13, 14): migrate_13_to_14,
    (14, 15): migrate_14_to_15,
    (15, 16): migrate_15_to_16,
    (16, 17): migrate_16_to_17,
    (17, 18): migrate_17_to_18,
    (18, 19): migrate_18_to_19,
    (19, 20): migrate_19_to_20,
    (20, 21): migrate_20_to_21,
    (21, 22): migrate_21_to_22,
    (22, 23): migrate_22_to_23,
    (23, 24): migrate_23_to_24,
    (24, 25): migrate_24_to_25,
    (25, 26): migrate_25_to_26,
    (26, 27): migrate_26_to_27,
    (27, 28): migrate_27_to_28,  # Phase 17 admin
    (28, 29): migrate_28_to_29,  # Phase 19 medlem/profil
    (29, 30): migrate_29_to_30,  # Phase 999.5 herd tracking
    (30, 31): migrate_30_to_31,  # Phase 999.8 genetics version
    (31, 32): migrate_31_to_32,  # Phase 999.8 genetics history
    (32, 33): migrate_32_to_33,  # history algorithm version
    (33, 34): migrate_33_to_34,  # genetics epoch
    (34, 35): migrate_34_to_35,  # ADR-0017 command log
    (35, 36): migrate_35_to_36,  # Individual.microchip
    (36, 37): migrate_36_to_37,  # billing address
    (37, 38): migrate_37_to_38,  # ADR-0019 retire replaced certificate PDFs
    (38, 39): migrate_38_to_39,  # audit_log IP retention index
    (39, 40): migrate_39_to_40,  # bank privacy reset
    (40, 41): migrate_40_to_41,  # mail queue
    (41, 42): migrate_41_to_42,  # intake queue
    (42, 43): migrate_42_to_43,  # intake queue retention
    (43, 44): migrate_43_to_44,  # buyer contact
    (44, 45): migrate_44_to_45,  # matrikel_audit actor NULL for the nightly job
    (45, 46): migrate_45_to_46,  # individual.rex
    (46, 47): migrate_46_to_47,  # the attester's name on the certificate check page
    (47, 48): migrate_47_to_48,  # unique Google identity
    (48, 49): migrate_48_to_49,  # one-time codes, previous addresses
    (49, 50): migrate_49_to_50,  # herd contact from the matrikel
    (50, 51): migrate_50_to_51,  # yearly report v2
    (51, 52): migrate_51_to_52,  # legal entity on membership
    (52, 53): migrate_52_to_53,  # notice.individual, buyer_contact.erased_email_hash
    (53, 54): migrate_53_to_54,  # account rules acceptance
    (54, 55): migrate_54_to_55,  # realised Ne per history year
    (55, 56): migrate_55_to_56,  # inbox_document.verified_at, verified_by, saved_certificate
    (56, 57): migrate_56_to_57,  # buyer_contact.email_notice_only
    (57, 58): migrate_57_to_58,  # the support account on the membership
}


def check_migrations():
    """
    Check if the database needs any migrations run and run those if that's the case.

    Concurrent callers (every gunicorn worker runs this at import) are
    serialized with a PostgreSQL advisory lock; the version is read after the
    lock is acquired, so late arrivals see the finished replay and no-op.
    """
    logger.debug("Checking for needed database migrations")

    if not isinstance(DATABASE, PostgresqlDatabase):
        _run_migrations()
        return

    DATABASE.execute_sql(
        "SELECT pg_advisory_lock(%s, hashtext(current_database()))",
        (MIGRATION_LOCK_KEY,),
    )
    try:
        _run_migrations()
        _repair_arsrapport_columns()
    finally:
        try:
            DATABASE.execute_sql(
                "SELECT pg_advisory_unlock(%s, hashtext(current_database()))",
                (MIGRATION_LOCK_KEY,),
            )
        except Exception:  # pylint: disable=broad-except
            # A dead connection has already released its session lock
            # server-side. Re-raising here would replace the original
            # migration error — turning e.g. a fatal ProgrammingError into
            # an OperationalError that connect() swallows.
            logger.warning("Failed to release migration advisory lock", exc_info=True)


def _repair_arsrapport_columns():
    """
    S5: the yearly report's migration keeps its number while the branch adds columns to it, so a database that ran
    an earlier 51 (dev and agent stacks) never replays it, and verify() fails on the missing column. The catalog is
    read first, so a healthy database takes no table lock at boot. A column the migration adds and the database lacks
    is added alone; a missing table of the yearly report's own reruns the migration's idempotent helper, here under
    the migration lock rather than in a worker's verify() and init(). Only when schema_history's 51 is this migration:
    another 51 is a collision of migration numbers, which a repair would hide, so it is logged and left alone. A
    database not bootstrapped yet has none of the tables and is init()'s.
    """
    tables = set(DATABASE.get_tables())
    if YearlyReportRound._meta.table_name not in tables:
        return
    gone = {model._meta.table_name for model in ARSRAPPORT_MODELS} - tables
    have = {t: {c.name for c in DATABASE.get_columns(t)} for t in {t for t, _, _ in _ADDED_COLUMNS}}  # empty: no table
    missing = [(t, name, ddl) for t, name, ddl in _ADDED_COLUMNS if have[t] and name not in have[t]]
    if not (gone or missing):
        return
    lacking = ", ".join(sorted(gone) + [f"{table}.{name}" for table, name, _ in missing])
    comment = SchemaHistory.select(SchemaHistory.comment).where(SchemaHistory.version == 51).scalar()
    if not (comment or "").startswith(ARSRAPPORT_51):
        logger.error("Schema version 51 is %r, not the yearly report's migration: not repairing %s", comment, lacking)
        return
    logger.warning("Repairing the yearly report's schema at version 51: %s", lacking)
    with DATABASE.atomic():
        if gone:
            _create_arsrapport_schema()
        else:
            # shortcut: the columns alone, not an FK, index or CHECK on them nor the helper's in-place changes (the
            # void CHECK swap); every 51 of this branch had those from the start. Rerun the helper if one changes.
            _add_columns(missing)


def _run_migrations():
    """
    Replay any missing migrations up to CURRENT_SCHEMA_VERSION.
    """
    current_version = None
    comment = None
    if SchemaHistory.table_exists():
        # the yearly report's migration under an older number (42 or 50 on its branch)
        comment = (
            SchemaHistory.select(SchemaHistory.comment)
            .where(SchemaHistory.version != 51, SchemaHistory.comment.startswith(ARSRAPPORT_51))
            .scalar()
        )
        current_version = SchemaHistory.select(fn.MAX(SchemaHistory.version)).scalar()  # pylint: disable=E1120
        # A bootstrap has no migration comment. Every buyer 50 (even before erased_email_hash) added
        # notice.individual_id; running 51–53 afterwards still never adds main's missing herd contact columns.
        if (
            current_version is not None
            and current_version >= 50
            and not {"contact_member_id", "contact_pending"} <= {c.name for c in DATABASE.get_columns("herd")}
            and "individual_id" in {c.name for c in DATABASE.get_columns("notice")}
        ):
            raise RuntimeError(
                "This database ran buyer mail as migration 50, now 53, and lacks main's herd contact migration "
                "and audit-log cleanup (49 -> 50). Rebuild a disposable development database from scratch. "
                "Är detta inte en utvecklingsdatabas: stoppa och utred migreringen."
            )
        # the organization fields' branch ran as 51 before the yearly report took the number: migrated (its own
        # comment) or bootstrapped (another 51 without any of the report's tables; main's 51 always has them).
        # Only version and comment: a version-1 history has no `applied` column yet.
        row_51 = SchemaHistory.select(SchemaHistory.comment).where(SchemaHistory.version == 51).tuples().first()
        report_tables = {model._meta.table_name for model in ARSRAPPORT_MODELS}
        organization_51 = SchemaHistory.select(SchemaHistory.version).where(
            SchemaHistory.version != 52, SchemaHistory.comment == ORGANIZATION_52
        )
        if organization_51.exists() or (
            row_51 is not None
            and not (row_51[0] or "").startswith(ARSRAPPORT_51)
            and not report_tables & set(DATABASE.get_tables())
        ):
            raise RuntimeError(
                "This development database ran the organization fields as migration 51, now 52, and lacks the "
                "yearly report v2 schema. Rebuild this development database from scratch. For a disposable Compose "
                "volume, run 'docker compose -p <dev-project> down -v' and bootstrap the database again.\n"
                "Är detta inte en utvecklingsdatabas: stoppa och fråga, kör inte down -v."
            )
    if comment is not None or (
        (current_version is None or current_version < 51)
        and {model._meta.table_name for model in ARSRAPPORT_MODELS}.intersection(DATABASE.get_tables())
    ):
        raise RuntimeError(
            "This development database uses the old yearly report v2 migration number (42 or 50, now 51). "
            "Rebuild this development database from scratch. For a disposable Compose volume, run "
            "'docker compose -p <dev-project> down -v' and bootstrap the database again.\n"
            "Är detta inte en utvecklingsdatabas: stoppa och fråga, kör inte down -v."
        )

    logger.debug(
        "Doing (if any) needed migrations from %s to %s",
        current_version,
        CURRENT_SCHEMA_VERSION,
    )

    if current_version == 53:
        buyer_columns = {c.name for c in DATABASE.get_columns("buyer_contact")}
        if "erased_email_hash" not in buyer_columns and {"rules_sha256", "rules_accepted_at", "rules_version"} <= {
            c.name for c in DATABASE.get_columns("hbuser")
        }:
            raise RuntimeError(
                "An earlier version of the login branch applied account rules as migration 53, now 54, "
                "and lacks buyer_contact.erased_email_hash. Rebuild the disposable development or CI database. "
                "Är detta inte en utvecklings- eller CI-databas: stoppa och utred migreringen."
            )
        # Earlier versions of the buyer mail migration lacked the invitation table or the review flag.
        if not BuyerInvitation.table_exists():
            with DATABASE.atomic():
                _create_buyer_invitations()
        if "email_review_pending" not in buyer_columns:
            _add_buyer_email_review()

    while current_version is None or current_version < CURRENT_SCHEMA_VERSION:
        next_version = (current_version if current_version else 0) + 1
        migration_func = MIGRATIONS.get((current_version, next_version))
        if migration_func is None:
            raise ValueError(f"No migration from {current_version} to {next_version}")
        logger.info(
            "Migrating from %s to %s",
            current_version,
            next_version,
        )
        migration_func()
        current_version = SchemaHistory.select(  # pylint: disable=E1120
            fn.MAX(SchemaHistory.version)
        ).scalar()


if is_connected():
    check_migrations()
