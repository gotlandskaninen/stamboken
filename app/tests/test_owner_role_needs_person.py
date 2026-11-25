"""Granting the owner role on a herd needs a person in the herd's membership linked to the account."""

import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest  # noqa: E402


class TestOwnerRoleNeedsPerson(DatabaseTest):
    def _grant(self, user, herd):
        return da.update_role({"action": "add", "role": "owner", "user": user.id, "herd": herd.id}, self.admin.uuid)

    def test_owner_refused_without_a_person_in_the_membership_and_given_with_one(self):
        membership = db.Membership.create(member_number=901, membership_status="active")
        db.Member.create(membership=membership, role="huvudmedlem", first_name="Anna", last_name="Svensson")
        herd = db.Herd.create(genebank=self.genebanks[0], herd="G901", membership=membership, is_active=True)
        user = da.register_user("bo@example.org", "pass", username="bo", fullname="Bo Svensson")

        with self.assertRaises(da.ValidationError) as refused:
            self._grant(user, herd)
        self.assertIn("kopplat till en person", refused.exception.detail)
        self.assertFalse(db.User.get_by_id(user.id).has_role("owner", herd.id))

        db.Member.create(membership=membership, role="familjemedlem", first_name="Bo", last_name="Svensson", user=user)
        self.assertEqual(self._grant(user, herd), {"status": "updated"})
        self.assertTrue(db.User.get_by_id(user.id).has_role("owner", herd.id))
