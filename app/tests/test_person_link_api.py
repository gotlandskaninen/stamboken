"""Phase 19 — kontokoppling: link / unlink / user search."""

import json
import threading
import unittest
from datetime import date
from unittest.mock import patch

import utils.data_access as da
import utils.database as db
import utils.matrikel as matrikel
from herdbook import APP, limiter

from tests.database_test import _USE_POSTGRES, DatabaseTest

limiter.enabled = False


class LinkApiBase(DatabaseTest):
    """Active membership owning G1 (self.herds[0]); huvudmedlem + familjemedlem + skotare, none linked."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.matrikel_user = da.register_user("matrikel@example.com", "pass", username="matrikel")
        self.matrikel_user.add_role("matrikel_admin", None)
        self.ms = db.Membership.create(member_number=6, membership_status="active")
        self.herds[0].membership = self.ms
        self.herds[0].save()
        self.main = db.Member.create(membership=self.ms, first_name="Anna", last_name="Lindqvist", role="huvudmedlem")
        self.family = db.Member.create(
            membership=self.ms, first_name="Erik", last_name="Lindqvist", role="familjemedlem"
        )
        self.skotare = db.Member.create(membership=self.ms, first_name="Maja", last_name="Berg", role="skotare")
        self.account = da.register_user("erik@example.com", "pass", username="erik.lindqvist")

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        # /api/login returns early when a session is already authenticated, so
        # switching users needs the logout first (repo idiom, cf.
        # test_admin_blueprint.py) — test_gating swaps manager → admin.
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def link(self, person_id, body):
        return self.client.post(
            f"/api/v2/persons/{person_id}/link-user", data=json.dumps(body), content_type="application/json"
        )


class TestLinkEndpoint(LinkApiBase):
    def test_family_without_grants_links_directly_with_audit_and_user_summary(self):
        self.login("matrikel")
        resp = self.link(self.family.id, {"user_id": self.account.id})
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertEqual(
            body["user"], {"id": self.account.id, "username": "erik.lindqvist", "email": "erik@example.com"}
        )
        self.assertEqual(db.Member.get_by_id(self.family.id).user_id, self.account.id)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_linked")
        self.assertEqual(audit.actor_id, self.matrikel_user.id)
        self.assertEqual(
            audit.payload,
            {"person_id": self.family.id, "user_id": self.account.id, "conveys_herd_ids": [], "source": "admin"},
        )
        self.assertNotIn("username", json.dumps(audit.payload))

    def test_main_member_link_requires_confirmation_with_conveys_herds(self):
        self.login("matrikel")
        resp = self.link(self.main.id, {"user_id": self.account.id})
        self.assertEqual(resp.status_code, 409, resp.data)
        body = resp.get_json()
        self.assertEqual(body["type"], "confirm-required")
        self.assertEqual(body["conveys_herds"], [{"id": self.herds[0].id, "herd": "G1", "herd_name": "Gotlandsherd1"}])
        self.assertIsNone(db.Member.get_by_id(self.main.id).user_id)

        resp = self.link(
            self.main.id, {"user_id": self.account.id, "confirm": True, "confirmed_herd_ids": [self.herds[0].id]}
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_linked").payload["conveys_herd_ids"],
            [self.herds[0].id],
        )
        self.assertIn(self.herds[0].id, db.User.get_by_id(self.account.id).effective_herd_ids())

    def test_confirm_with_wrong_or_missing_ids_is_refused(self):
        self.login("matrikel")
        self.assertEqual(self.link(self.main.id, {"user_id": self.account.id, "confirm": True}).status_code, 409)
        self.assertEqual(
            self.link(
                self.main.id, {"user_id": self.account.id, "confirm": True, "confirmed_herd_ids": [999]}
            ).status_code,
            409,
        )
        self.assertIsNone(db.Member.get_by_id(self.main.id).user_id)

    def test_no_warning_when_account_already_owns_the_herd(self):
        self.account.add_role("owner", self.herds[0].id)
        self.login("matrikel")
        self.assertEqual(self.link(self.main.id, {"user_id": self.account.id}).status_code, 200)

    def test_grant_outside_membership_conveys_that_herd_only(self):
        matrikel.create_grant(self.family, self.herds[1], None, self.admin)
        self.login("matrikel")
        body = self.link(self.family.id, {"user_id": self.account.id}).get_json()
        self.assertEqual([h["id"] for h in body["conveys_herds"]], [self.herds[1].id])

    def test_skotare_without_grants_and_inactive_memberships_convey_nothing(self):
        self.login("matrikel")
        self.assertEqual(self.link(self.skotare.id, {"user_id": self.account.id}).status_code, 200)
        for status in ("pending", "inactive", "friexemplar"):
            other = db.Membership.create(membership_status=status)
            self.herds[1].membership = other
            self.herds[1].save()
            main = db.Member.create(membership=other, first_name="X", last_name=status, role="huvudmedlem")
            user = da.register_user(f"{status}@example.com", "pass", username=status)
            self.assertEqual(self.link(main.id, {"user_id": user.id}).status_code, 200, status)

    def test_headless_membership_promotion_goes_through_main_member_endpoint_only(self):
        """Promoting a LINKED family member conveys the membership's herds —
        only swap_main_member() (membership lock + main_member_changed audit) may do it, never PATCH role."""
        self.login("matrikel")
        self.assertEqual(self.link(self.family.id, {"user_id": self.account.id}).status_code, 200)
        self.main.end_date = date.today()  # headless: the active main is gone (e.g. anonymised)
        self.main.save()
        resp = self.client.patch(
            f"/api/v2/persons/{self.family.id}",
            data=json.dumps({"role": "huvudmedlem"}),
            content_type="application/json",
        )
        self.assertEqual(
            (resp.status_code, resp.get_json()["title"]), (409, "Huvudmedlem sätts via main-member-endpointen")
        )
        self.assertEqual(db.Member.get_by_id(self.family.id).role, "familjemedlem")
        resp = self.client.post(
            f"/api/v2/memberships/{self.ms.id}/main-member",
            data=json.dumps({"person_id": self.family.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Member.get_by_id(self.family.id).role, "huvudmedlem")
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "main_member_changed")
        self.assertEqual(audit.payload, {"previous_person_id": None, "new_person_id": self.family.id})
        self.assertIn(self.herds[0].id, db.User.get_by_id(self.account.id).effective_herd_ids())

    def test_404s(self):
        self.login("matrikel")
        self.assertEqual(self.link(99999, {"user_id": self.account.id}).status_code, 404)
        self.assertEqual(self.link(self.family.id, {"user_id": 99999}).status_code, 404)

    def test_409_ended_person_inactive_user_and_already_linked(self):
        self.login("matrikel")
        self.skotare.end_date = date.today()
        self.skotare.save()
        resp = self.link(self.skotare.id, {"user_id": self.account.id})
        self.assertEqual((resp.status_code, resp.get_json()["title"]), (409, "Personen är avslutad"))

        self.account.is_active = False
        self.account.save()
        resp = self.link(self.family.id, {"user_id": self.account.id})
        self.assertEqual((resp.status_code, resp.get_json()["title"]), (409, "Kontot är inaktivt"))
        self.account.is_active = True
        self.account.save()

        self.assertEqual(self.link(self.family.id, {"user_id": self.account.id}).status_code, 200)
        other = da.register_user("other@example.com", "pass", username="other")
        resp = self.link(self.family.id, {"user_id": other.id})
        self.assertEqual((resp.status_code, resp.get_json()["title"]), (409, "Personen har redan ett konto"))
        self.skotare.end_date = None  # re-activate: the ended-person guard runs first
        self.skotare.save()
        resp = self.link(self.skotare.id, {"user_id": self.account.id})
        self.assertEqual((resp.status_code, resp.get_json()["title"]), (409, "Kontot är redan kopplat"))
        self.assertIn("Erik Lindqvist i medlemskap nr 6", resp.get_json()["detail"])

    def test_ended_holder_named_with_end_date_then_unlink_releases(self):
        self.login("matrikel")
        self.link(self.family.id, {"user_id": self.account.id})
        self.family.end_date = date(2026, 1, 2)
        self.family.save()
        resp = self.link(self.skotare.id, {"user_id": self.account.id})
        self.assertIn("(avslutad 2026-01-02)", resp.get_json()["detail"])
        resp = self.client.delete(f"/api/v2/persons/{self.family.id}/link-user")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNone(resp.get_json()["user"])
        self.assertEqual(self.link(self.skotare.id, {"user_id": self.account.id}).status_code, 200)

    def test_unlink_404_409_and_audit(self):
        self.login("matrikel")
        self.assertEqual(self.client.delete("/api/v2/persons/99999/link-user").status_code, 404)
        resp = self.client.delete(f"/api/v2/persons/{self.family.id}/link-user")
        self.assertEqual((resp.status_code, resp.get_json()["title"]), (409, "Personen har inget kopplat konto"))
        self.link(self.family.id, {"user_id": self.account.id})
        self.assertEqual(self.client.delete(f"/api/v2/persons/{self.family.id}/link-user").status_code, 200)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_unlinked")
        self.assertEqual(audit.payload, {"person_id": self.family.id, "user_id": self.account.id, "source": "admin"})

    def test_gating(self):
        self.login("man")  # gene-bank manager: matrikel READ only
        self.assertEqual(self.link(self.family.id, {"user_id": self.account.id}).status_code, 403)
        self.assertEqual(self.client.get("/api/v2/users/search?q=erik").status_code, 403)
        self.login("admin")
        self.assertEqual(self.client.get("/api/v2/users/search?q=erik").status_code, 200)

    def test_detail_get_renders_user_summary_for_linked_active_and_ended_persons(self):
        self.login("matrikel")
        self.link(self.family.id, {"user_id": self.account.id})
        self.family.end_date = date.today()
        self.family.save()
        persons = {p["id"]: p for p in self.client.get(f"/api/v2/members/{self.ms.id}").get_json()["persons"]}
        self.assertEqual(persons[self.family.id]["user"]["username"], "erik.lindqvist")
        self.assertIsNone(persons[self.main.id]["user"])

    def test_cache_invalidation_hits_conveyed_and_lost_genebanks_only(self):
        """Cache: per-genebank invalidation after commit, nothing on an empty delta."""
        self.login("matrikel")
        second = da.register_user("m2@example.com", "pass", username="m2")
        with patch("utils.matrikel.trigger_invalidation") as invalidate:
            self.assertEqual(self.link(self.family.id, {"user_id": self.account.id}).status_code, 200)
            invalidate.assert_not_called()
            resp = self.link(
                self.main.id, {"user_id": second.id, "confirm": True, "confirmed_herd_ids": [self.herds[0].id]}
            )
            self.assertEqual(resp.status_code, 200, resp.data)
            invalidate.assert_called_once_with(self.genebanks[0].id)
            invalidate.reset_mock()
            self.assertEqual(self.client.delete(f"/api/v2/persons/{self.main.id}/link-user").status_code, 200)
            invalidate.assert_called_once_with(self.genebanks[0].id)
            invalidate.reset_mock()
            self.assertEqual(self.client.delete(f"/api/v2/persons/{self.family.id}/link-user").status_code, 200)
            invalidate.assert_not_called()

    def test_cache_invalidation_failure_never_undoes_a_committed_link(self):
        """Invalidation is best-effort after commit: a throwing
        cache must not 500 a durable link/unlink."""
        self.login("matrikel")
        second = da.register_user("m3@example.com", "pass", username="m3")
        with patch("utils.matrikel.trigger_invalidation", side_effect=RuntimeError("cache down")) as invalidate:
            resp = self.link(
                self.main.id, {"user_id": second.id, "confirm": True, "confirmed_herd_ids": [self.herds[0].id]}
            )
            self.assertEqual(resp.status_code, 200, resp.data)
            invalidate.assert_called_once_with(self.genebanks[0].id)
            self.assertEqual(db.Member.get_by_id(self.main.id).user_id, second.id)
            self.assertEqual(self.client.delete(f"/api/v2/persons/{self.main.id}/link-user").status_code, 200)
        self.assertIsNone(db.Member.get_by_id(self.main.id).user_id)

    @unittest.skipUnless(_USE_POSTGRES, "FOR UPDATE serialisation needs PostgreSQL")
    def test_concurrent_links_of_one_user_to_two_persons_yield_one_link(self):
        errors, barrier = [], threading.Barrier(2)
        admin_id, account_id = self.admin.id, self.account.id

        def worker(person_id):
            try:
                barrier.wait(timeout=10)
                matrikel.link_member_user(person_id, account_id, actor=db.User.get_by_id(admin_id), mode="admin")
            except matrikel.LinkError as exc:
                errors.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        threads = [threading.Thread(target=worker, args=(pid,)) for pid in (self.family.id, self.skotare.id)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        for t in threads:
            self.assertFalse(t.is_alive(), "worker still blocked after the join timeout")
        self.assertEqual(len(errors), 1)
        self.assertEqual(db.Member.select().where(db.Member.user == account_id).count(), 1)


class TestUserSearch(LinkApiBase):
    def test_search_shape_cap_and_filters(self):
        for i in range(12):
            da.register_user(f"erik{i}@example.com", "pass", username=f"erik{i:02d}")
        inactive = da.register_user("erik-off@example.com", "pass", username="erik-off")
        inactive.is_active = False
        inactive.save()
        self.login("matrikel")
        self.assertEqual(self.client.get("/api/v2/users/search?q=e").status_code, 400)
        body = self.client.get("/api/v2/users/search?q=ERIK").get_json()
        self.assertEqual(len(body["users"]), 10)
        self.assertEqual(set(body["users"][0]), {"id", "username", "email"})
        self.assertNotIn("erik-off", [u["username"] for u in body["users"]])
        self.assertEqual([u["username"] for u in body["users"]], sorted(u["username"] for u in body["users"]))
        body = self.client.get("/api/v2/users/search?q=erik@ex").get_json()
        self.assertEqual([u["username"] for u in body["users"]], ["erik.lindqvist"])

    def test_search_denies_plain_members(self):
        """Only admin/matrikel_admin may search accounts — a linked
        ordinary member gets 403."""
        self.family.user = self.account
        self.family.save()
        self.login("erik.lindqvist")
        self.assertEqual(self.client.get("/api/v2/users/search?q=erik").status_code, 403)
