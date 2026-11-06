"""Tests for herd-access-grant domain functions and endpoints (Member Model v2)."""

import json
from datetime import date, datetime, timedelta

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting in tests — these classes log in more than
# 5 times/minute when the file runs in isolation (see Test Conventions).
limiter.enabled = False


class GrantTestBase(DatabaseTest):
    """Membership with main + skotare person (linked to a user), one owned herd."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.membership = db.Membership.create(member_number=6, membership_status="active")
        self.main = db.Member.create(
            membership=self.membership,
            first_name="Maja",
            last_name="Huvudsson",
            email="maja@example.com",
            role="huvudmedlem",
        )
        self.caretaker_user = da.register_user("sune@example.com", "pass", username="sune")
        self.caretaker = db.Member.create(
            membership=self.membership,
            first_name="Sune",
            last_name="Skötarsson",
            email="sune@example.com",
            role="skotare",
            user=self.caretaker_user,
        )
        self.herd = self.herds[0]
        self.herd.membership = self.membership
        self.herd.save()
        self.matadmin = da.register_user("matadmin@example.com", "pass", username="matadmin")
        self.matadmin.add_role("matrikel_admin", None)

    def login(self, username="matadmin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def create_grant_http(self, person_id=None, body=None):
        pid = person_id if person_id is not None else self.caretaker.id
        return self.client.post(
            f"/api/v2/persons/{pid}/grants",
            data=json.dumps(body if body is not None else {"herd_id": self.herd.id}),
            content_type="application/json",
        )


class TestGrantDomainFunctions(GrantTestBase):
    def test_grant_is_active_matrix(self):
        grant = db.HerdAccessGrant.create(member=self.caretaker, herd=self.herd, granted_by=self.admin)
        self.assertTrue(matrikel.grant_is_active(grant))
        grant.valid_until = date.today()
        self.assertTrue(matrikel.grant_is_active(grant), "valid THROUGH valid_until")
        grant.valid_until = date.today() - timedelta(days=1)
        self.assertFalse(matrikel.grant_is_active(grant), "expired")
        grant.valid_until = None
        grant.revoked_at = datetime.now()
        self.assertFalse(matrikel.grant_is_active(grant), "revoked")

    def test_grant_inactive_when_person_soft_deleted(self):
        grant = db.HerdAccessGrant.create(member=self.caretaker, herd=self.herd, granted_by=self.admin)
        self.caretaker.end_date = date.today()
        self.caretaker.save()
        fresh = db.HerdAccessGrant.get_by_id(grant.id)
        self.assertFalse(matrikel.grant_is_active(fresh))

    def test_create_grant_role_defaults(self):
        grant = matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        self.assertIsNotNone(grant.valid_until, "skotare default is +1 year")
        self.assertEqual(grant.valid_until.year, date.today().year + 1)
        main_grant = matrikel.create_grant(self.main, self.herd, None, self.admin)
        self.assertIsNone(main_grant.valid_until, "huvudmedlem/familjemedlem default is NULL")

    def test_create_grant_regrant_reuses_row(self):
        grant = matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        matrikel.revoke_grant(grant, self.admin)
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)
        regrant = matrikel.create_grant(self.caretaker, self.herd, date.today() + timedelta(days=30), self.admin)
        self.assertEqual(regrant.id, grant.id)
        self.assertIsNone(regrant.revoked_at)
        self.assertEqual(regrant.valid_until, date.today() + timedelta(days=30))
        count = (
            db.HerdAccessGrant.select()
            .where(
                db.HerdAccessGrant.member == self.caretaker,
                db.HerdAccessGrant.herd == self.herd,
            )
            .count()
        )
        self.assertEqual(count, 1)

    def test_create_grant_inactive_person_raises(self):
        self.caretaker.end_date = date.today()
        self.caretaker.save()
        with self.assertRaises(ValueError):
            matrikel.create_grant(self.caretaker, self.herd, None, self.admin)

    def test_renew_revoked_raises(self):
        grant = matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        matrikel.revoke_grant(grant, self.admin)
        fresh = db.HerdAccessGrant.get_by_id(grant.id)
        with self.assertRaises(ValueError):
            matrikel.renew_grant(fresh, self.admin)

    def test_transitions_audited(self):
        grant = matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        matrikel.renew_grant(grant, self.admin)
        matrikel.revoke_grant(grant, self.admin)
        actions = [a.action for a in db.MatrikelAudit.select().order_by(db.MatrikelAudit.id)]
        self.assertEqual(actions, ["grant_created", "grant_renewed", "grant_revoked"])


class TestGrantEffectiveAccess(GrantTestBase):
    def test_grant_lifecycle_reflected_in_effective_herd_ids(self):
        def herd_ids():
            return db.User.get_by_id(self.caretaker_user.id).effective_herd_ids()

        self.assertNotIn(self.herd.id, herd_ids())
        grant = matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        self.assertIn(self.herd.id, herd_ids())
        matrikel.revoke_grant(grant, self.admin)
        self.assertNotIn(self.herd.id, herd_ids())
        regrant = matrikel.create_grant(self.caretaker, self.herd, date.today() - timedelta(days=1), self.admin)
        self.assertNotIn(self.herd.id, herd_ids(), "expired grant must not authorize")
        matrikel.renew_grant(regrant, self.admin)
        self.assertIn(self.herd.id, herd_ids(), "renewal restores access")


class TestGrantEndpoints(GrantTestBase):
    def test_anonymous_401(self):
        self.assertEqual(self.create_grant_http().status_code, 401)

    def test_owner_403(self):
        self.login("owner")
        self.assertEqual(self.create_grant_http().status_code, 403)

    def test_manager_403(self):
        self.login("man")
        self.assertEqual(self.create_grant_http().status_code, 403)

    def test_admin_unrestricted_herd_201(self):
        # herds[1] is NOT owned by the membership — matrikel_admin/admin
        # may still grant on it (the own-herd restriction is handled elsewhere).
        self.login("admin")
        resp = self.create_grant_http(body={"herd_id": self.herds[1].id})
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_create_grant_default_valid_until(self):
        self.login()
        resp = self.create_grant_http()
        self.assertEqual(resp.status_code, 201, resp.data)
        data = resp.get_json()
        self.assertTrue(data["active"])
        self.assertEqual(date.fromisoformat(data["valid_until"]).year, date.today().year + 1)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "grant_created")
        self.assertEqual(audit.payload["person_id"], self.caretaker.id)

    def test_create_grant_validation_errors(self):
        self.login()
        self.assertEqual(self.create_grant_http(person_id=99999).status_code, 404)
        self.assertEqual(self.create_grant_http(body={}).status_code, 400)
        self.assertEqual(self.create_grant_http(body={"herd_id": 99999}).status_code, 404)
        resp = self.create_grant_http(body={"herd_id": self.herd.id, "valid_until": "inte-ett-datum"})
        self.assertEqual(resp.status_code, 400)

    def test_renew_endpoint_plus_one_year(self):
        grant = matrikel.create_grant(self.caretaker, self.herd, date.today() + timedelta(days=10), self.admin)
        self.login()
        resp = self.client.post(f"/api/v2/grants/{grant.id}/renew")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertEqual(date.fromisoformat(data["valid_until"]).year, date.today().year + 1)

    def test_renew_revoked_409(self):
        grant = matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        matrikel.revoke_grant(grant, self.admin)
        self.login()
        resp = self.client.post(f"/api/v2/grants/{grant.id}/renew")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.content_type, "application/problem+json")

    def test_revoke_endpoint(self):
        grant = matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        self.login()
        resp = self.client.delete(f"/api/v2/grants/{grant.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertIsNotNone(data["revoked_at"])
        self.assertFalse(data["active"])
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)


class TestSuspensionCandidates(GrantTestBase):
    """matrikel.suspension_candidates() — the spec's Phase 9 query."""

    def test_workspace_person_without_active_grant_is_candidate(self):
        # caretaker has a Workspace login but no grant at all → candidate.
        self.caretaker.workspace_email = "sune.skotarsson@gotlandskaninen.se"
        self.caretaker.save()
        candidates = matrikel.suspension_candidates()
        self.assertIn(self.caretaker.id, [p.id for p in candidates])

    def test_active_grant_excludes_candidate(self):
        self.caretaker.workspace_email = "sune.skotarsson@gotlandskaninen.se"
        self.caretaker.save()
        matrikel.create_grant(self.caretaker, self.herd, None, self.admin)
        candidates = matrikel.suspension_candidates()
        self.assertNotIn(self.caretaker.id, [p.id for p in candidates])

    def test_person_without_workspace_email_never_candidate(self):
        # main has no workspace_email → never a suspension candidate.
        candidates = matrikel.suspension_candidates()
        self.assertNotIn(self.main.id, [p.id for p in candidates])
