"""Granting the owner role on a herd needs a person in the herd's active membership linked to the account."""

import utils.data_access as da
import utils.database as db

from tests.test_legacy_api_contracts import FlaskTest  # noqa: E402


class TestOwnerRoleNeedsPerson(FlaskTest):
    def setUp(self):
        super().setUp()
        self.membership = db.Membership.create(member_number=901, membership_status="active")
        db.Member.create(membership=self.membership, role="huvudmedlem", first_name="Anna", last_name="Svensson")
        self.herd = db.Herd.create(genebank=self.genebanks[0], herd="G901", membership=self.membership, is_active=True)
        self.bo = da.register_user("bo@example.org", "pass", username="bo", fullname="Bo Svensson")

    def _grants(self, herd):
        """The v2 admin panel and the legacy route, as admin: [(status, json, owns afterwards)]."""
        results = []
        with self.app as ctx:
            self.login(ctx, self.admin)
            for path, body in (
                (
                    "/api/v2/admin/role",
                    {"operation": "add", "user_id": self.bo.id, "role": {"level": "owner", "herd": herd.id}},
                ),
                ("/api/manage/role", {"action": "add", "role": "owner", "user": self.bo.id, "herd": herd.id}),
            ):
                resp = ctx.post(path, json=body)
                results.append((resp.status_code, resp.get_json(), self._owns(herd)))
                self.bo.remove_role("owner", herd.id)  # the second route starts from the same state
                self.bo.save()
        return results

    def _owns(self, herd):
        return db.User.get_by_id(self.bo.id).has_role("owner", herd.id)

    def _assert_refused(self, herd, problem_type, text):
        for status, body, owns in self._grants(herd):
            self.assertEqual((status, body["type"], owns), (409, problem_type, False))
            self.assertIn(text, body["detail"])

    def test_refused_without_a_person_in_the_membership(self):
        self._assert_refused(self.herd, "owner-requires-person", "kopplat till en person")

    def test_refused_while_the_membership_is_not_active(self):
        db.Member.create(membership=self.membership, role="familjemedlem", first_name="Bo", last_name="S", user=self.bo)
        for status in ("inactive", "pending"):
            with self.subTest(status=status):
                db.Membership.update(membership_status=status).where(db.Membership.id == self.membership.id).execute()
                self._assert_refused(self.herd, "owner-requires-person", "medlemskapet måste vara aktivt")

    def test_refused_for_a_herd_without_membership(self):
        loose = db.Herd.create(genebank=self.genebanks[0], herd="G902", is_active=True)
        db.Member.create(membership=self.membership, role="familjemedlem", first_name="Bo", last_name="S", user=self.bo)
        self._assert_refused(
            loose,
            "herd-without-membership",
            "Besättningen är inte kopplad till något medlemskap. "
            "Koppla den i matrikeln innan du ger rollen besättningsägare.",
        )

    def test_unknown_herd_has_its_own_problem(self):
        unknown = db.Herd(id=999999)  # never saved
        for status, body, owns in self._grants(unknown):
            self.assertEqual((status, body["type"], owns), (404, "herd-not-found", False))
            self.assertIn("finns inte", body["detail"])

    def test_given_to_a_linked_familjemedlem(self):
        db.Member.create(membership=self.membership, role="familjemedlem", first_name="Bo", last_name="S", user=self.bo)
        for status, body, owns in self._grants(self.herd):
            self.assertEqual((status, body, owns), (200, {"status": "updated"}, True))

    def test_an_ended_person_does_not_count(self):
        db.Member.create(
            membership=self.membership,
            role="familjemedlem",
            first_name="Bo",
            last_name="S",
            user=self.bo,
            end_date="2026-01-01",
        )
        self._assert_refused(self.herd, "owner-requires-person", "kopplat till en person")
