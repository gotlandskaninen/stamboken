"""
Create test users for legacy Playwright tests.

Called from CI workflow and the local-production bootstrap (stamboken-drift).
Reuses the same user definitions as the bootstrap script.

Usage (inside API container):
    python3 -m cli.create_test_users
"""

import os
import sys

from utils import data_access as da
from utils.database import Genebank, Herd, Individual, Member, User, latest_ht_per_individual, not_voided
from utils.matrikel import new_membership
from utils.membership_lifecycle import Status


def _herd_has_individuals(herd):
    """True if some non-voided individual's CURRENT herd (latest active tracking row) is `herd`."""
    latest = latest_ht_per_individual().alias("latest_ht")
    return (
        Individual.select(Individual.id)
        .join(latest, on=(Individual.id == latest.c.i_id))
        .where(latest.c.rank == 1, latest.c.herd == herd.id)
        .where(not_voided())
        .exists()
    )


def find_herd_with_rabbits(genebank):
    """Find the first active herd with individuals for a genebank."""
    if not genebank:
        return None
    for herd in Herd.select().where(Herd.genebank == genebank, Herd.is_active == True):  # noqa: E712
        if _herd_has_individuals(herd):
            return herd
    return None


def find_empty_herd(genebank):
    """Find the first active herd without individuals.

    Falls back to CREATING a dedicated fixture herd (G9990) when the loaded
    dump has none — a real prod dump may lack empty active herds, and
    test-empty's owner role (which the admin e2e suite depends on) was then
    silently skipped (found 2026-08-03 on local-production).
    """
    if not genebank:
        return None
    for herd in Herd.select().where(Herd.genebank == genebank, Herd.is_active == True):  # noqa: E712
        if not _herd_has_individuals(herd):
            return herd
    fixture_code = "G9990" if genebank.name == "Gotlandskanin" else "M9990"
    herd = Herd.select().where(Herd.genebank == genebank, Herd.herd == fixture_code).first()
    if herd is None:
        herd = Herd.create(
            genebank=genebank,
            herd=fixture_code,
            herd_name="E2E tom besättning",
            is_active=True,
        )
        print(f"  Created empty fixture herd {fixture_code}")
    return herd


def create_test_users():
    # Same production check as settings.refuse_committed_signing_key.
    if os.environ.get("FLASK_ENV") == "production":
        print("ERROR: refusing to create test users with public passwords in production.", file=sys.stderr)
        sys.exit(1)

    gk = Genebank.select().where(Genebank.name == "Gotlandskanin").first()
    mk = Genebank.select().where(Genebank.name == "Mellerudskanin").first()

    if not gk:
        print("ERROR: Genebank 'Gotlandskanin' not found. Run 'flask seed create' first.", file=sys.stderr)
        sys.exit(1)

    gk_herd = find_herd_with_rabbits(gk)
    mk_herd = find_herd_with_rabbits(mk)
    gk_empty = find_empty_herd(gk)

    if not gk_herd:
        print("ERROR: No active herd with individuals found for Gotlandskanin.", file=sys.stderr)
        sys.exit(1)

    users = [
        {
            "email": "test-admin@test.local",
            "password": "test-admin-pass",
            "username": "test-admin",
            "fullname": "Test Admin",
            "roles": [("admin", None)],
            # The CMS keys on google_email; stands in for a Google login
            # so the seeded CMS_ADMIN_EMAIL allowlist row works locally.
            "google_email": "test-admin@test.local",
        },
        {
            "email": "test-gk-mgr@test.local",
            "password": "test-gk-pass",
            "username": "test-gk-manager",
            "fullname": "Test GK Manager",
            "roles": [("manager", gk.id if gk else None)],
        },
        {
            "email": "test-mk-mgr@test.local",
            "password": "test-mk-pass",
            "username": "test-mk-manager",
            "fullname": "Test MK Manager",
            "roles": [("manager", mk.id if mk else None)],
        },
        {
            "email": "test-gk-owner@test.local",
            "password": "test-gk-owner-pass",
            "username": "test-gk-owner",
            "fullname": "Test GK Uppfödare",
            "roles": [("owner", gk_herd.id if gk_herd else None)],
        },
        {
            # Promoted fixture: v2_prod_access=True exercises the demo->prod default
            # and the promoted-path E2E. Same privileges as
            # test-gk-owner; the flag is a UX/rollout gate, not an authz boundary.
            "email": "test-gk-owner-promoted@test.local",
            "password": "test-gk-owner-promoted-pass",
            "username": "test-gk-owner-promoted",
            "fullname": "Test GK Uppfödare (promoted)",
            "roles": [("owner", gk_herd.id if gk_herd else None)],
            "v2_prod_access": True,
        },
        {
            "email": "test-mk-owner@test.local",
            "password": "test-mk-owner-pass",
            "username": "test-mk-owner",
            "fullname": "Test MK Uppfödare",
            "roles": [("owner", mk_herd.id if mk_herd else None)],
        },
        {
            "email": "test-dual@test.local",
            "password": "test-dual-pass",
            "username": "test-dual",
            "fullname": "Test Dual Uppfödare",
            "roles": [
                ("owner", gk_herd.id if gk_herd else None),
                ("owner", mk_herd.id if mk_herd else None),
            ],
        },
        {
            "email": "test-empty@test.local",
            "password": "test-empty-pass",
            "username": "test-empty",
            "fullname": "Test Tom Besättning",
            "roles": [("owner", gk_empty.id if gk_empty else None)],
        },
        {
            "email": "test-member@test.local",
            "password": "test-member-pass",
            "username": "test-member",
            "fullname": "Test Member",
            "roles": [],
        },
        {
            "email": "test-family@test.local",
            "password": "test-family-pass",
            "username": "test-family",
            "fullname": "Test Family",
            "roles": [],
        },
    ]

    # All users get viewer on both genebanks (matches Google OAuth registration)
    default_privileges = [
        {"level": "viewer", "genebank": gk.id},
    ]
    if mk:
        default_privileges.append({"level": "viewer", "genebank": mk.id})

    created = 0
    for u in users:
        existing = User.select().where(User.email == u["email"]).first()
        if existing:
            print(f"  Exists: {u['username']}")
            continue
        try:
            user = da.register_user(
                u["email"],
                u["password"],
                username=u["username"],
                fullname=u["fullname"],
                validated=True,
                privileges=default_privileges,
            )
            for level, target in u["roles"]:
                if level == "admin":
                    user.add_role(level)
                elif target is not None:
                    user.add_role(level, target)
            if u.get("v2_prod_access"):
                user.v2_prod_access = True
            user.google_email = u.get("google_email")
            user.save()
            roles_str = ", ".join(level for level, _ in u["roles"])
            print(f"  Created: {u['username']} ({roles_str})")
            created += 1
        except Exception as e:
            print(f"  ERROR creating {u['username']}: {e}", file=sys.stderr)
            sys.exit(1)

    # Link a Member person row (v2: under a Membership) to test-member so
    # Playwright can exercise /stamboken/profil without the Phase 9 OAuth
    # provisioning flow.
    # Rows are resolved through their USER link (unique since migrate_28_to_29),
    # never by the non-unique contact e-mail alone.
    test_member = User.select().where(User.email == "test-member@test.local").first()
    if test_member is not None:
        # A row carrying the fixture's contact e-mail but linked to ANOTHER
        # account is an ambiguous seed state. Refuse, naming both
        # accounts: the e-mail fallback below would otherwise adopt that row,
        # and when test-member already has a row of its own the run used to
        # print "already present" and skip the conflict entirely.
        crossed = (
            Member.select()
            .where(
                Member.email == "test-member@test.local",
                Member.user.is_null(False),
                Member.user != test_member,
            )
            .first()
        )
        if crossed is not None:
            print(
                f"  ERROR: member row {crossed.id} (test-member@test.local) is linked to user "
                f"{crossed.user_id}, but test-member is user {test_member.id} — unlink one of them "
                "or clear the row before re-running",
                file=sys.stderr,
            )
            sys.exit(1)
        existing = Member.select().where(Member.user == test_member).first()
        if existing is None:
            # Fallback: a row an older run created without a user link.
            existing = Member.select().where(Member.email == "test-member@test.local").first()
        if existing is None:
            membership = new_membership(Status.ACTIVE)
            if gk_herd is not None and gk_herd.membership_id is None:
                gk_herd.membership = membership
                gk_herd.save()
            Member.create(
                first_name="Playwright",
                last_name="TestMember",
                email="test-member@test.local",
                # Test fixture bypasses Phase 9. We link directly so
                # Playwright can hit /stamboken/profil without OAuth.
                workspace_email=None,
                membership=membership,
                role="huvudmedlem",
                user=test_member,  # direct link, NOT via auto-link helper
            )
            print("  Created linked Member for test-member")
        elif existing.role != "huvudmedlem":
            print(
                f"  ERROR: member row {existing.id} for test-member is not a huvudmedlem — fix the seed data",
                file=sys.stderr,
            )
            sys.exit(1)
        elif existing.user_id is None:
            # If a previous run created the Member without a user link, fix it.
            existing.user = test_member  # the unique index makes a link elsewhere fail loudly
            existing.save()
            print("  Re-linked existing Member to test-member")
        else:
            print("  Linked Member for test-member already present")

    # Phase 19: a familjemedlem on the same membership, linked to test-family,
    # so profil.spec.ts can assert the read-only cards + Huvudmedlem name.
    # Rows are resolved through their USER link (unique), never by the
    # non-unique contact e-mail alone.
    test_family = User.select().where(User.email == "test-family@test.local").first()
    # The ACTIVE huvudmedlem row, never an ended or demoted one:
    # the familjemedlem fixture hangs off this row's membership, and profil.spec
    # asserts the huvudmedlem name through it.
    owner_row = (
        Member.select()
        .where(Member.user == test_member, Member.end_date.is_null(True), Member.role == "huvudmedlem")
        .first()
        if test_member is not None
        else None
    )
    if test_family is None:
        print(
            "  ERROR: user test-family@test.local is missing — the familjemedlem fixture cannot be seeded; "
            "fix the user creation above and re-run",
            file=sys.stderr,
        )
        sys.exit(1)
    if owner_row is None:
        linked = Member.select().where(Member.user == test_member).first() if test_member is not None else None
        if linked is not None:
            print(
                f"  ERROR: member row {linked.id} is linked to test-member@test.local but is not an active "
                f"huvudmedlem (role={linked.role}, end_date={linked.end_date}) — the familjemedlem fixture "
                "needs that membership; fix the seed data and re-run",
                file=sys.stderr,
            )
        else:
            print(
                "  ERROR: no member row is linked to test-member@test.local — the familjemedlem fixture needs "
                "that membership; fix the test-member block above and re-run",
                file=sys.stderr,
            )
        sys.exit(1)
    family_row = Member.select().where(Member.user == test_family).first()
    if family_row is None:
        family_row = (
            Member.select()
            .where(Member.email == "test-family@test.local", Member.membership == owner_row.membership)
            .first()
        )
    if family_row is None:
        Member.create(
            first_name="Playwright",
            last_name="Family",
            email="test-family@test.local",
            membership=owner_row.membership,
            role="familjemedlem",
            user=test_family,  # fixture — direct link, exempt from the confirm rule
        )
        print("  Created linked familjemedlem for test-family")
    elif family_row.membership_id != owner_row.membership_id or family_row.role != "familjemedlem":
        print(
            f"  ERROR: member row {family_row.id} for test-family is not a familjemedlem on "
            f"test-member's membership {owner_row.membership_id} — fix the seed data",
            file=sys.stderr,
        )
        sys.exit(1)
    elif family_row.user_id is None:
        family_row.user = test_family  # the unique index makes a link elsewhere fail loudly
        family_row.save()
        print("  Re-linked existing familjemedlem to test-family")
    elif family_row.user_id != test_family.id:
        print(
            f"  ERROR: member row {family_row.id} (test-family@test.local) is linked to user "
            f"{family_row.user_id}, not to test-family (user {test_family.id}) — unlink it or clear the "
            "row before re-running",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print("  Linked familjemedlem for test-family already present")

    print(f"  Done: {created} created, {len(users) - created} existing")


if __name__ == "__main__":
    create_test_users()
