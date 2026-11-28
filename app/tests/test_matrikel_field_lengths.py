"""
R029 (#294): the matrikel's write routes answer 400 for a value too long for its column or of the wrong type, never
500 (a DataError at the write, or .strip() on a number), and write nothing.
"""

import json
from datetime import datetime

import utils.database as db
from herdbook import APP

from tests.test_my_membership_api import MyMembershipTestBase


class TestMatrikelFieldLengths(MyMembershipTestBase):
    def setUp(self):
        super().setUp()
        # As in production: an unhandled exception is a 500 response, not a raise.
        self._propagate = APP.config.get("PROPAGATE_EXCEPTIONS")
        APP.config["PROPAGATE_EXCEPTIONS"] = False

    def tearDown(self):
        APP.config["PROPAGATE_EXCEPTIONS"] = self._propagate
        super().tearDown()

    def send(self, user, method, url, body):
        self.login(user)
        resp = getattr(self.client, method)(url, data=json.dumps(body), content_type="application/json")
        self.client.get("/api/logout")
        return resp

    def assert_refused(self, resp, field=None):
        self.assertEqual(resp.status_code, 400, resp.get_data(as_text=True))
        if field is not None:
            self.assertEqual(resp.get_json().get("field"), field)

    def test_reject_reason_must_be_text(self):
        pending = db.MemberApplication.create(
            first_name="A", last_name="A", email="a@example.com", gdpr_consented_at=datetime.now(), status="pending"
        )
        resp = self.send("man", "post", f"/api/v2/member-applications/{pending.id}/reject", {"rejection_reason": 123})
        self.assert_refused(resp)
        self.assertEqual(db.MemberApplication.get_by_id(pending.id).status, "pending")

    def test_profile_phone_too_long(self):
        resp = self.send("maja", "patch", "/api/v2/members/me/contact", {"phone": "0" * 51})
        self.assert_refused(resp, "phone")
        self.assertNotEqual(db.Member.get_by_id(self.main.id).phone, "0" * 51)

    def test_profile_phone_at_the_limit_is_saved(self):
        resp = self.send("maja", "patch", "/api/v2/members/me/contact", {"phone": "0" * 50})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(db.Member.get_by_id(self.main.id).phone, "0" * 50)

    def test_new_membership_name_too_long(self):
        before = db.Membership.select().count()
        resp = self.send("admin", "post", "/api/v2/memberships", {"first_name": "x" * 101, "last_name": "Y"})
        self.assert_refused(resp, "first_name")
        self.assertEqual(db.Membership.select().count(), before)

    def test_admin_adds_person_with_phone_too_long(self):
        before = db.Member.select().count()
        url = f"/api/v2/memberships/{self.membership.id}/persons"
        resp = self.send("admin", "post", url, {"first_name": "A", "last_name": "B", "phone": "0" * 51})
        self.assert_refused(resp, "phone")
        self.assertEqual(db.Member.select().count(), before)

    def test_admin_patches_person_with_last_name_too_long(self):
        resp = self.send("admin", "patch", f"/api/v2/persons/{self.family.id}", {"last_name": "y" * 101})
        self.assert_refused(resp, "last_name")
        self.assertNotEqual(db.Member.get_by_id(self.family.id).last_name, "y" * 101)

    def test_main_member_adds_person_with_email_too_long(self):
        before = db.Member.select().count()
        email = "a" * 250 + "@example.com"
        body = {"first_name": "A", "last_name": "B", "email": email}
        resp = self.send("maja", "post", "/api/v2/my-membership/persons", body)
        self.assert_refused(resp, "email")
        self.assertEqual(db.Member.select().count(), before)

    def test_trimmed_length_counts(self):
        url = f"/api/v2/memberships/{self.membership.id}/persons"
        resp = self.send("admin", "post", url, {"first_name": " " + "x" * 100 + " ", "last_name": "B"})
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
