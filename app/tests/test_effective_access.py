"""Tests for User.effective_herd_ids() and its consumers (Member Model v2).

Effective herd access is the single derivation of herd-level rights:
(a) grandfathered legacy {"level": "owner", "herd": id} privilege entries,
(b) herds owned by the membership whose ACTIVE person row (end_date IS
    NULL) with role 'huvudmedlem' is linked to the user,
(c) herds of ACTIVE grants (revoked_at IS NULL AND (valid_until IS NULL
    OR valid_until >= today)) held by the user's active person rows.

Pure model tests (no HTTP) — no limiter import needed.
"""

from datetime import date, datetime, timedelta

import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest


class EffectiveAccessTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        # self.membership owns seeded herd G1 (self.herds[0], genebank Gotland).
        self.membership = db.Membership.create(member_number=42)
        self.herds[0].membership = self.membership
        self.herds[0].save()

    def _user(self, email):
        return da.register_user(email, "pass", username=email)

    def _person(self, user=None, role="huvudmedlem", end_date=None, membership=None):
        return db.Member.create(
            first_name="Test",
            last_name="Person",
            genebank=self.genebanks[0],
            membership=membership or self.membership,
            role=role,
            end_date=end_date,
            user=user,
        )


class TestEffectiveHerdIds(EffectiveAccessTest):
    def test_no_access_yields_empty_set_and_none_is_owner(self):
        user = self._user("nobody@example.com")
        self.assertEqual(user.effective_herd_ids(), set())
        self.assertIsNone(user.is_owner)

    def test_legacy_owner_privilege_grandfathered(self):
        user = self._user("legacy@example.com")
        user.add_role("owner", self.herds[1].id)
        self.assertEqual(user.effective_herd_ids(), {self.herds[1].id})
        self.assertEqual(user.is_owner, [self.herds[1].herd])

    def test_main_member_derives_membership_herds(self):
        user = self._user("main@example.com")
        self._person(user=user, role="huvudmedlem")
        self.assertEqual(user.effective_herd_ids(), {self.herds[0].id})
        self.assertEqual(user.is_owner, [self.herds[0].herd])

    def test_inactive_membership_conveys_no_rights(self):
        """An inactive membership must not confer herd access via either the
        main-member branch or the grant branch — and flipping it
        back to active restores both."""
        main_user = self._user("inact-main@example.com")
        self._person(user=main_user, role="huvudmedlem")
        caretaker_user = self._user("inact-skotare@example.com")
        caretaker = self._person(user=caretaker_user, role="skotare")
        db.HerdAccessGrant.create(member=caretaker, herd=self.herds[0], granted_by=self.admin)
        self.assertEqual(main_user.effective_herd_ids(), {self.herds[0].id})
        self.assertEqual(caretaker_user.effective_herd_ids(), {self.herds[0].id})

        self.membership.membership_status = "inactive"
        self.membership.save()
        self.assertEqual(main_user.effective_herd_ids(), set())
        self.assertIsNone(main_user.is_owner)
        self.assertEqual(caretaker_user.effective_herd_ids(), set())

        self.membership.membership_status = "active"
        self.membership.save()
        self.assertEqual(main_user.effective_herd_ids(), {self.herds[0].id})
        self.assertEqual(caretaker_user.effective_herd_ids(), {self.herds[0].id})

    def test_family_member_without_grant_has_no_herd_access(self):
        user = self._user("family@example.com")
        self._person(user=user, role="familjemedlem")
        self.assertEqual(user.effective_herd_ids(), set())
        self.assertIsNone(user.is_owner)

    def test_active_grant_valid_through_today(self):
        user = self._user("skotare@example.com")
        person = self._person(user=user, role="skotare")
        db.HerdAccessGrant.create(
            member=person,
            herd=self.herds[1],
            valid_until=date.today(),  # valid THROUGH the date
            granted_by=self.admin,
        )
        self.assertIn(self.herds[1].id, user.effective_herd_ids())

    def test_null_valid_until_grant_is_active_until_revoked(self):
        user = self._user("familjegrant@example.com")
        person = self._person(user=user, role="familjemedlem")
        db.HerdAccessGrant.create(member=person, herd=self.herds[1], granted_by=self.admin)
        self.assertIn(self.herds[1].id, user.effective_herd_ids())

    def test_expired_grant_stops_authorizing(self):
        user = self._user("expired@example.com")
        person = self._person(user=user, role="skotare")
        db.HerdAccessGrant.create(
            member=person,
            herd=self.herds[1],
            valid_until=date.today() - timedelta(days=1),
            granted_by=self.admin,
        )
        self.assertEqual(user.effective_herd_ids(), set())

    def test_revoked_grant_stops_authorizing(self):
        user = self._user("revoked@example.com")
        person = self._person(user=user, role="skotare")
        db.HerdAccessGrant.create(
            member=person,
            herd=self.herds[1],
            revoked_at=datetime.now(),
            granted_by=self.admin,
        )
        self.assertEqual(user.effective_herd_ids(), set())

    def test_soft_deleted_person_loses_all_derived_access(self):
        user = self._user("gone@example.com")
        person = self._person(user=user, role="huvudmedlem", end_date=date.today())
        db.HerdAccessGrant.create(member=person, herd=self.herds[1], granted_by=self.admin)
        self.assertEqual(user.effective_herd_ids(), set())

    def test_union_of_all_three_sources(self):
        user = self._user("union@example.com")
        user.add_role("owner", self.herds[2].id)  # (a) legacy JSON entry
        person = self._person(user=user, role="huvudmedlem")  # (b) owns herds[0]
        db.HerdAccessGrant.create(member=person, herd=self.herds[1], granted_by=self.admin)  # (c)
        self.assertEqual(
            user.effective_herd_ids(),
            {self.herds[0].id, self.herds[1].id, self.herds[2].id},
        )
        self.assertCountEqual(user.is_owner, [h.herd for h in self.herds])


class TestEffectiveAccessConsumers(EffectiveAccessTest):
    def _caretaker_with_grant(self, email, herd):
        """User whose ONLY access is a grant — their membership owns no herds."""
        user = self._user(email)
        caretaker_membership = db.Membership.create(member_number=77)
        person = self._person(user=user, role="skotare", membership=caretaker_membership)
        db.HerdAccessGrant.create(member=person, herd=herd, granted_by=self.admin)
        return user

    def test_filtered_dict_grant_only_caretaker_sees_private_fields(self):
        user = self._caretaker_with_grant("caretaker@example.com", self.herds[0])
        data = self.herds[0].filtered_dict(user)
        self.assertEqual(data.get("name"), "owner1")  # name_privacy="private"

    def test_filtered_dict_other_herds_get_authenticated_level(self):
        user = self._caretaker_with_grant("caretaker2@example.com", self.herds[0])
        data = self.herds[1].filtered_dict(user)
        self.assertEqual(data.get("name"), "owner2")  # name_privacy="authenticated"
        self.assertNotIn("www", data)  # www_privacy="private"

    def test_filtered_dict_viewer_gets_authenticated_level(self):
        """A plain viewer (the default role of every new account) is not 'private'."""
        self.herds[1].bank_account_number = "1234-5"  # bank_account_number_privacy="private"
        self.herds[1].save()
        for herd in self.herds[:2]:  # both in the viewer's genebank
            data = herd.filtered_dict(self.viewer)
            self.assertNotIn("bank_account_number", data)
            self.assertFalse([k for k in data if k.endswith("_privacy")])
        self.assertNotIn("name", self.herds[0].filtered_dict(self.viewer))  # name_privacy="private"
        self.assertEqual(self.herds[0].filtered_dict(self.viewer).get("email"), "o@h1")  # "authenticated"
        self.assertEqual(self.herds[1].filtered_dict(self.viewer).get("name"), "owner2")  # "authenticated"

    def test_filtered_dict_manager_of_genebank_gets_private_level(self):
        self.herds[1].bank_account_number = "1234-5"  # bank_account_number_privacy="private"
        self.herds[1].save()
        data = self.herds[1].filtered_dict(self.manager)
        self.assertEqual(data.get("www"), "www2")  # www_privacy="private"
        self.assertEqual(data.get("bank_account_number"), "1234-5")

    def test_filtered_dict_manager_of_other_genebank_gets_public_level(self):
        user = self._user("othermanager@example.se")
        user.add_role("manager", self.genebanks[1].id)
        data = self.herds[0].filtered_dict(user)
        self.assertNotIn("name", data)  # name_privacy="private"
        self.assertEqual(data.get("www"), "www1")  # www_privacy="public"

    def test_filtered_dict_viewer_who_is_also_manager_gets_private_level(self):
        """The manager role wins whichever order the roles are stored in."""
        for roles in (("viewer", "manager"), ("manager", "viewer")):
            user = self._user(f"{roles[0]}-{roles[1]}@example.se")
            for level in roles:
                user.add_role(level, self.genebanks[0].id)
            self.assertEqual(self.herds[1].filtered_dict(user).get("www"), "www2", roles)

    def test_filtered_dict_viewer_who_owns_the_herd_gets_private_level(self):
        user = self._user("viewerowner@example.se")
        user.add_role("viewer", self.genebanks[0].id)
        user.add_role("owner", self.herds[0].id)
        self.assertEqual(self.herds[0].filtered_dict(user).get("name"), "owner1")  # name_privacy="private"
        self.assertNotIn("www", self.herds[1].filtered_dict(user))  # someone else's herd: authenticated

    def test_filtered_dict_viewer_of_other_genebank_stays_public(self):
        data = self.herds[2].filtered_dict(self.viewer)  # viewer of Gotland, herd is Mellerud's
        self.assertEqual(data.get("name"), "Owner3")  # name_privacy="public"
        self.assertNotIn("www", data)  # www_privacy="authenticated"

    def test_filtered_dict_unrelated_user_stays_public(self):
        user = self._user("stranger@example.com")
        data = self.herds[0].filtered_dict(user)
        self.assertNotIn("name", data)  # name_privacy="private"
        self.assertNotIn("email", data)  # email_privacy="authenticated"
        self.assertEqual(data.get("www"), "www1")  # www_privacy="public"

    def test_accessible_genebanks_includes_granted_herd_genebank(self):
        # herds[2] belongs to genebank Mellerud (self.genebanks[1]).
        user = self._caretaker_with_grant("cross@example.com", self.herds[2])
        self.assertIn(self.genebanks[1].id, user.accessible_genebanks)

    def test_accessible_genebanks_main_member(self):
        user = self._user("mainbank@example.com")
        self._person(user=user, role="huvudmedlem")
        self.assertEqual(user.accessible_genebanks, [self.genebanks[0].id])

    def test_frontend_data_is_owner_derives_from_effective_access(self):
        user = self._user("fe@example.com")
        self._person(user=user, role="huvudmedlem")
        data = user.frontend_data()
        self.assertEqual(data["is_owner"], [self.herds[0].herd])
