"""Tests for the /api/v2/my-membership self-service endpoints (Member Model v2)."""

import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
from blueprints import memberships as memberships_routes  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from peewee import IntegrityError

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting in tests — these classes log in more than
# 5 times/minute when the file runs in isolation (see Test Conventions).
limiter.enabled = False


class MyMembershipTestBase(DatabaseTest):
    """Membership with a linked main member, a linked family member and one owned herd."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.main_user = da.register_user("maja@example.com", "pass", username="maja")
        self.family_user = da.register_user("frank@example.com", "pass", username="frank")
        self.unlinked_user = da.register_user("ute@example.com", "pass", username="ute")
        self.membership = db.Membership.create(member_number=6, membership_status="active")
        self.main = db.Member.create(
            membership=self.membership,
            first_name="Maja",
            last_name="Huvudsson",
            email="maja@example.com",
            role="huvudmedlem",
            user=self.main_user,
        )
        self.family = db.Member.create(
            membership=self.membership,
            first_name="Frank",
            last_name="Familjesson",
            email="frank@example.com",
            role="familjemedlem",
            user=self.family_user,
        )
        self.own_herd = self.herds[0]
        self.own_herd.membership = self.membership
        self.own_herd.save()
        # herds[1] stays without membership — the "not our herd" case.
        self.other_herd = self.herds[1]

    def login(self, username="maja", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def post_json(self, url, body):
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def _foreign_membership(self):
        other = db.Membership.create(member_number=9, membership_status="active")
        person = db.Member.create(membership=other, first_name="Olle", last_name="Utomsson", role="huvudmedlem")
        grant = matrikel.create_grant(person, self.other_herd, None, self.admin)
        return other, person, grant


class TestResolveOwnMembership(MyMembershipTestBase):
    def test_resolves_active_person(self):
        self.assertEqual(matrikel.resolve_own_membership(self.main_user).id, self.main.id)

    def test_none_for_unlinked(self):
        self.assertIsNone(matrikel.resolve_own_membership(self.unlinked_user))

    def test_ignores_soft_deleted_rows(self):
        self.family.end_date = date.today()
        self.family.save()
        self.assertIsNone(matrikel.resolve_own_membership(self.family_user))

    def test_one_user_one_active_row_invariant(self):
        """migrate_28_to_29's partial unique index: a second person row for a
        linked user is rejected at the schema level, so resolve_own_membership
        always sees at most one candidate (identity)."""
        other = db.Membership.create(member_number=7, membership_status="active")
        with self.assertRaises(IntegrityError):
            with db.DB_PROXY.atomic():
                db.Member.create(
                    membership=other,
                    first_name="Frank",
                    last_name="Familjesson",
                    email="frank@example.com",
                    role="huvudmedlem",
                    user=self.family_user,
                )
        self.assertEqual(matrikel.resolve_own_membership(self.family_user).id, self.family.id)


class TestMyMembershipGet(MyMembershipTestBase):
    def test_unauthenticated_401(self):
        self.assertEqual(self.client.get("/api/v2/my-membership").status_code, 401)

    def test_unlinked_404(self):
        self.login("ute")
        resp = self.client.get("/api/v2/my-membership")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.content_type, "application/problem+json")
        resp = self.post_json("/api/v2/my-membership/persons", {"first_name": "X", "last_name": "Y"})
        self.assertEqual(resp.status_code, 404)

    def test_main_member_sees_persons_grants_and_herds(self):
        matrikel.create_grant(self.family, self.own_herd, None, self.admin)
        self.login()
        resp = self.client.get("/api/v2/my-membership")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertTrue(data["is_main_member"])
        ms = data["membership"]
        self.assertEqual(ms["member_number"], 6)
        self.assertEqual([h["id"] for h in ms["herds"]], [self.own_herd.id])
        self.assertEqual(len(ms["persons"]), 2)
        family_entry = next(p for p in ms["persons"] if p["id"] == self.family.id)
        self.assertEqual(len(family_entry["grants"]), 1)
        self.assertTrue(family_entry["grants"][0]["active"])

    def test_family_member_sees_own_entry_only(self):
        self.login("frank")
        resp = self.client.get("/api/v2/my-membership")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertFalse(data["is_main_member"])
        self.assertEqual([p["id"] for p in data["membership"]["persons"]], [self.family.id])

    def test_linked_accounts_are_id_only_on_self_service(self):
        """A huvudmedlem sees that a person has an account, never its login e-mail/username.

        ``workspace_email`` is the provisioned login address (Phase 8 identity
        model) and stays admin-only too.
        """
        self.family.workspace_email = "frank.familjesson@gotlandskaninen.se"
        self.family.save()
        self.login()
        resp = self.client.get("/api/v2/my-membership")
        self.assertEqual(resp.status_code, 200, resp.data)
        persons = resp.get_json()["membership"]["persons"]
        linked = [p for p in persons if p["user_id"]]
        self.assertEqual(len(linked), 2)
        for p in linked:
            self.assertEqual(p["user"], {"id": p["user_id"]})
            self.assertNotIn("workspace_email", p)
        # The matrikel routes keep the account details the Konto column renders.
        # (switching users needs the logout first — repo idiom, cf. test_person_link_api)
        self.client.get("/api/logout")
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/v2/memberships/{self.membership.id}",
            data=json.dumps({"notes": "konto-kolumn"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        admin_entry = next(p for p in resp.get_json()["persons"] if p["id"] == self.family.id)
        self.assertEqual(admin_entry["user"]["username"], "frank")
        self.assertEqual(admin_entry["user"]["email"], "frank@example.com")
        self.assertEqual(admin_entry["workspace_email"], "frank.familjesson@gotlandskaninen.se")

    def test_keepers_notes_and_consent_bookkeeping_stay_out_of_self_service(self):
        """Notes, payment note and consent bookkeeping are the keeper's, not profil data.

        Neither a familjemedlem nor a huvudmedlem may read them on the GET, and the
        person echoes of POST and DELETE use the same serializer.
        """
        self.membership.notes = "intern R030"
        self.membership.payment_note = "Ej betalt R030"
        self.membership.publication_consent = {"email": True}
        self.membership.save()
        self.family.notes = "admin-anteckning R030"
        self.family.gdpr_consented_at = datetime.now()
        self.family.save()
        membership_keys = {"notes", "payment_note", "publication_consent"}
        person_keys = {"notes", "gdpr_consented_at", "workspace_email"}

        def leaked(membership):
            found = membership_keys & membership.keys()
            for person in membership["persons"]:
                found |= {f"person.{key}" for key in person_keys & person.keys()}
            return found

        self.login("frank")  # familjemedlem
        ms = self.client.get("/api/v2/my-membership").get_json()["membership"]
        self.assertEqual(leaked(ms), set())
        self.client.get("/api/logout")

        self.login()  # huvudmedlem
        ms = self.client.get("/api/v2/my-membership").get_json()["membership"]
        self.assertEqual(leaked(ms), set())
        self.assertEqual(len(ms["persons"]), 2)
        added = self.post_json("/api/v2/my-membership/persons", {"first_name": "Nina", "last_name": "Nysson"})
        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(person_keys & added.get_json().keys(), set())
        removed = self.client.delete(f"/api/v2/my-membership/persons/{self.family.id}")
        self.assertEqual(removed.status_code, 200, removed.data)
        self.assertEqual(person_keys & removed.get_json().keys(), set())

        # The matrikel routes keep the keeper's view.
        self.client.get("/api/logout")
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/v2/memberships/{self.membership.id}",
            data=json.dumps({"notes": "intern R030"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        admin_view = resp.get_json()
        self.assertEqual(admin_view["payment_note"], "Ej betalt R030")
        family_entry = next(p for p in admin_view["persons"] if p["id"] == self.family.id)
        self.assertEqual(family_entry["notes"], "admin-anteckning R030")


class TestMyMembershipMutations(MyMembershipTestBase):
    def test_family_member_403_on_all_mutations(self):
        grant = matrikel.create_grant(self.family, self.own_herd, None, self.admin)
        self.login("frank")
        resp = self.post_json("/api/v2/my-membership/persons", {"first_name": "X", "last_name": "Y"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(self.client.delete(f"/api/v2/my-membership/persons/{self.family.id}").status_code, 403)
        resp = self.post_json(f"/api/v2/my-membership/persons/{self.family.id}/grants", {"herd_id": self.own_herd.id})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/my-membership/grants/{grant.id}/renew").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/v2/my-membership/grants/{grant.id}").status_code, 403)

    def test_demoted_main_member_403_on_mutations(self):
        """After a main-member swap the ex-main must be rejected — the role
        check runs under the membership lock (TOCTOU regression)."""
        matrikel.swap_main_member(self.membership, self.family, self.admin)
        self.login()  # maja — no longer huvudmedlem
        resp = self.post_json("/api/v2/my-membership/persons", {"first_name": "X", "last_name": "Y"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.content_type, "application/problem+json")

    def test_add_person_with_duplicate_warning_and_actor_audit(self):
        self.login()
        resp = self.post_json(
            "/api/v2/my-membership/persons",
            {"first_name": "Nina", "last_name": "Nysson", "email": "frank@example.com", "role": "skotare"},
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        data = resp.get_json()
        self.assertEqual(data["role"], "skotare")
        self.assertTrue(data["duplicate_contact_email"])
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_added")
        self.assertEqual(audit.actor_id, self.main_user.id)

    def test_duplicate_email_warning_is_scoped_to_the_own_membership(self):
        """Self-service must not reveal whether an address exists in another membership.

        The household's own addresses still warn; the matrikel route keeps the
        registry-wide warning the keepers rely on.
        """
        other = db.Membership.create(member_number=9, membership_status="active")
        db.Member.create(
            membership=other,
            first_name="Olle",
            last_name="Utomsson",
            email="olle@foreign.example.com",
            role="huvudmedlem",
        )
        db.Member.create(
            membership=other,
            first_name="Sofia",
            last_name="Utomsson",
            email="sofia@foreign.example.com",
            role="familjemedlem",
        )
        self.login()  # maja, huvudmedlem of membership 6
        signal = []
        for first, email in (
            ("P", "olle@foreign.example.com"),
            ("Q", "nobody@fresh.example.com"),
            ("R", "frank@example.com"),
        ):
            resp = self.post_json(
                "/api/v2/my-membership/persons", {"first_name": first, "last_name": "X", "email": email}
            )
            self.assertEqual(resp.status_code, 201, resp.data)
            signal.append(resp.get_json()["duplicate_contact_email"])
        self.assertEqual(
            signal,
            [False, False, True],
            "duplicate_contact_email for (foreign-membership email, unused email, own-membership email)",
        )

        self.client.get("/api/logout")
        self.login("admin", "pass")
        resp = self.post_json(
            f"/api/v2/memberships/{self.membership.id}/persons",
            {
                "first_name": "S",
                "last_name": "X",
                "email": "sofia@foreign.example.com",
            },  # exists only in the foreign household
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.get_json()["duplicate_contact_email"])

    def test_add_person_role_huvudmedlem_400(self):
        self.login()
        resp = self.post_json(
            "/api/v2/my-membership/persons",
            {"first_name": "Kupp", "last_name": "Makare", "role": "huvudmedlem"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_grant_own_herd_defaults(self):
        skotare = db.Member.create(
            membership=self.membership, first_name="Sune", last_name="Skötarsson", role="skotare"
        )
        self.login()
        resp = self.post_json(f"/api/v2/my-membership/persons/{skotare.id}/grants", {"herd_id": self.own_herd.id})
        self.assertEqual(resp.status_code, 201, resp.data)
        data = resp.get_json()
        self.assertEqual(date.fromisoformat(data["valid_until"]).year, date.today().year + 1)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "grant_created")
        self.assertEqual(audit.actor_id, self.main_user.id)

    def test_grant_foreign_herd_403(self):
        self.login()
        resp = self.post_json(f"/api/v2/my-membership/persons/{self.family.id}/grants", {"herd_id": self.other_herd.id})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.content_type, "application/problem+json")

    def test_renew_plus_one_year(self):
        grant = matrikel.create_grant(self.family, self.own_herd, date.today() + timedelta(days=10), self.admin)
        self.login()
        resp = self.client.post(f"/api/v2/my-membership/grants/{grant.id}/renew")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertEqual(date.fromisoformat(data["valid_until"]).year, date.today().year + 1)

    def test_renew_foreign_grant_404(self):
        _other, _person, foreign_grant = self._foreign_membership()
        self.login()
        resp = self.client.post(f"/api/v2/my-membership/grants/{foreign_grant.id}/renew")
        self.assertEqual(resp.status_code, 404)

    def test_renew_admin_issued_foreign_herd_grant_403(self):
        """Own person, foreign herd: an admin-issued grant on another
        membership's herd must not be renewable via self-service (that
        would extend access self-service cannot create)."""
        grant = matrikel.create_grant(self.family, self.other_herd, date.today() + timedelta(days=10), self.admin)
        self.login()
        resp = self.client.post(f"/api/v2/my-membership/grants/{grant.id}/renew")
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(
            db.HerdAccessGrant.get_by_id(grant.id).valid_until,
            date.today() + timedelta(days=10),
        )

    def test_revoke_grant(self):
        grant = matrikel.create_grant(self.family, self.own_herd, None, self.admin)
        self.login()
        resp = self.client.delete(f"/api/v2/my-membership/grants/{grant.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)

    def test_delete_person_soft_and_revokes(self):
        grant = matrikel.create_grant(self.family, self.own_herd, None, self.admin)
        self.login()
        resp = self.client.delete(f"/api/v2/my-membership/persons/{self.family.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNotNone(db.Member.get_by_id(self.family.id).end_date)
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)

    def test_delete_person_response_is_account_id_only(self):
        """The DELETE echo must not leak the removed person's login e-mail/username."""
        self.family.workspace_email = "frank.familjesson@gotlandskaninen.se"
        self.family.save()
        self.login()
        resp = self.client.delete(f"/api/v2/my-membership/persons/{self.family.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.get_json()["user"], {"id": self.family_user.id})
        self.assertNotIn("workspace_email", resp.get_json())

    def test_delete_self_main_409(self):
        self.login()
        resp = self.client.delete(f"/api/v2/my-membership/persons/{self.main.id}")
        self.assertEqual(resp.status_code, 409)
        self.assertIsNone(db.Member.get_by_id(self.main.id).end_date)

    def test_delete_person_foreign_membership_404(self):
        _other, person, _grant = self._foreign_membership()
        self.login()
        resp = self.client.delete(f"/api/v2/my-membership/persons/{person.id}")
        self.assertEqual(resp.status_code, 404)
        self.assertIsNone(db.Member.get_by_id(person.id).end_date)


class TestMainMemberAuthorizationUnderTheLock(MyMembershipTestBase):
    """resolve_own_membership() runs before _require_main_member is
    granted the membership lock, so the linkage it resolved can be gone by the
    time the mutation runs. Each test freezes that request-start resolve to the
    row as it looked before the competing write and asserts the route re-decides
    on the row it re-reads under the lock. One person mutation and one grant
    mutation stand in for all five — they share the single gate."""

    PERSON_BODY = {"first_name": "Ny", "last_name": "Person", "role": "familjemedlem"}

    def _stale_post(self, stale, path, body):
        with patch.object(memberships_routes, "resolve_own_membership", return_value=stale):
            return self.post_json(path, body)

    def test_add_person_refuses_after_the_account_is_unlinked(self):
        self.login()
        stale = db.Member.get_by_id(self.main.id)
        matrikel.unlink_member_user(self.main.id, actor=self.admin)
        resp = self._stale_post(stale, "/api/v2/my-membership/persons", self.PERSON_BODY)
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(resp.get_json()["title"], "Kontot är inte längre kopplat")
        self.assertEqual(db.Member.select().where(db.Member.membership == self.membership).count(), 2)

    def test_add_person_refuses_an_anonymized_row(self):
        """Raw update: anonymize_person() also detaches, so the placeholder-name
        pair is written directly to exercise the is_anonymized() branch on its
        own — a still-linked erased row must not administer the membership."""
        self.login()
        stale = db.Member.get_by_id(self.main.id)
        db.Member.update(first_name=matrikel.ANONYMIZED_FIRST_NAME, last_name=matrikel.ANONYMIZED_LAST_NAME).where(
            db.Member.id == self.main.id
        ).execute()
        resp = self._stale_post(stale, "/api/v2/my-membership/persons", self.PERSON_BODY)
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.get_json()["title"], "Kontot är inte längre kopplat")
        self.assertEqual(db.Member.select().where(db.Member.membership == self.membership).count(), 2)

    def test_create_grant_refuses_after_the_account_is_unlinked(self):
        self.login()
        stale = db.Member.get_by_id(self.main.id)
        matrikel.unlink_member_user(self.main.id, actor=self.admin)
        resp = self._stale_post(
            stale, f"/api/v2/my-membership/persons/{self.family.id}/grants", {"herd_id": self.own_herd.id}
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.get_json()["title"], "Kontot är inte längre kopplat")
        self.assertFalse(db.HerdAccessGrant.select().where(db.HerdAccessGrant.member == self.family).exists())
