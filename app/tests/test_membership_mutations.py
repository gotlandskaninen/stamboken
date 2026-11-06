"""Tests for /api/v2/memberships and /api/v2/persons mutations (Member Model v2)."""

import json
from datetime import datetime
from unittest.mock import patch

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
from blueprints import memberships as memberships_routes  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting in tests — these classes log in more than
# 5 times/minute when the file runs in isolation (see Test Conventions).
limiter.enabled = False


def _make_membership(number=6):
    """One membership with an active huvudmedlem and one familjemedlem."""
    membership = db.Membership.create(
        member_number=number,
        membership_status="active",
        address="Storgatan 1",
    )
    main = db.Member.create(
        membership=membership,
        first_name="Maja",
        last_name="Huvudsson",
        email="maja@example.com",
        role="huvudmedlem",
    )
    family = db.Member.create(
        membership=membership,
        first_name="Frank",
        last_name="Familjesson",
        email="frank@example.com",
        role="familjemedlem",
    )
    return membership, main, family


class TestMatrikelDomainFunctions(DatabaseTest):
    """Direct tests for the domain functions in utils/matrikel.py."""

    def setUp(self):
        super().setUp()
        self.membership, self.main, self.family = _make_membership()

    def test_add_person_creates_row_and_audit(self):
        person = matrikel.add_person(
            self.membership,
            {"first_name": "Nina", "last_name": "Nysson", "email": "nina@example.com", "role": "skotare"},
            self.admin,
        )
        self.assertEqual(person.membership_id, self.membership.id)
        self.assertEqual(person.role, "skotare")
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_added")
        self.assertEqual(audit.membership_id, self.membership.id)
        self.assertEqual(audit.payload["person_id"], person.id)

    def test_add_person_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            matrikel.add_person(
                self.membership,
                {"first_name": "X", "last_name": "Y", "role": "styrelsemedlem"},
                self.admin,
            )

    def test_soft_delete_person_revokes_grants(self):
        grant = db.HerdAccessGrant.create(member=self.family, herd=self.herds[0], granted_by=self.admin)
        matrikel.soft_delete_person(self.family, self.admin)
        self.assertIsNotNone(db.Member.get_by_id(self.family.id).end_date)
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)
        self.assertTrue(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_removed").exists())

    def test_soft_delete_last_main_member_raises(self):
        with self.assertRaises(ValueError):
            matrikel.soft_delete_person(self.main, self.admin)
        self.assertIsNone(db.Member.get_by_id(self.main.id).end_date)

    def test_swap_main_member_atomic(self):
        matrikel.swap_main_member(self.membership, self.family, self.admin)
        self.assertEqual(db.Member.get_by_id(self.main.id).role, "familjemedlem")
        self.assertEqual(db.Member.get_by_id(self.family.id).role, "huvudmedlem")
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "main_member_changed")
        self.assertEqual(audit.payload["new_person_id"], self.family.id)
        self.assertEqual(audit.payload["previous_person_id"], self.main.id)

    def test_swap_main_member_rejects_foreign_person(self):
        _other_membership, other_main, _other_family = _make_membership(number=7)
        with self.assertRaises(ValueError):
            matrikel.swap_main_member(self.membership, other_main, self.admin)

    def test_anonymize_person(self):
        user = da.register_user("fam@example.com", "pass", username="fam")
        self.family.user = user
        self.family.save()
        grant = db.HerdAccessGrant.create(member=self.family, herd=self.herds[0], granted_by=self.admin)
        matrikel.anonymize_person(self.family, self.admin)
        person = db.Member.get_by_id(self.family.id)
        self.assertEqual(person.first_name, "Borttagen")
        self.assertEqual(person.last_name, "person")
        self.assertIsNone(person.email)
        self.assertIsNone(person.phone)
        self.assertIsNone(person.workspace_email)
        self.assertIsNone(person.gdpr_consented_at)
        self.assertIsNone(person.notes)
        self.assertIsNone(person.user_id)
        self.assertIsNotNone(person.end_date)
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)
        self.assertTrue(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_anonymized").exists())

    def test_anonymize_clears_household_address_only_with_the_last_active_person(self):
        """The address stays while someone is active in the household and goes
        with the last one; payment_note is accounting history and stays."""
        self.membership.postal_code, self.membership.city = "623 55", "Visby"
        self.membership.notes, self.membership.payment_note = "Anna bor ensam", "betalt 2026"
        self.membership.save()

        matrikel.anonymize_person(self.family, self.admin)
        ms = db.Membership.get_by_id(self.membership.id)
        self.assertEqual(
            (ms.address, ms.postal_code, ms.city, ms.notes), ("Storgatan 1", "623 55", "Visby", "Anna bor ensam")
        )

        matrikel.anonymize_person(self.main, self.admin)
        ms = db.Membership.get_by_id(self.membership.id)
        self.assertEqual((ms.address, ms.postal_code, ms.city, ms.notes), (None, None, None, None))
        self.assertEqual(ms.payment_note, "betalt 2026")

    def test_anonymize_redacts_the_household_address_from_membership_audits(self):
        """A membership PATCH audits the old and new address (before v29 also as
        postal_address); clearing the row must not leave them in matrikel_audit.
        payment_note is not cleared, so it stays."""
        matrikel.anonymize_person(self.family, self.admin)
        patched = matrikel.write_matrikel_audit(
            self.admin,
            "membership_updated",
            self.membership,
            {
                "before": {"address": "Storgatan 1", "city": "Visby", "payment_note": "betalt 2025"},
                "after": {"address": "Kungsgatan 2", "postal_address": "623 55 Visby", "payment_note": "betalt 2026"},
            },
        )
        other = _make_membership(number=9)[0]
        elsewhere = matrikel.write_matrikel_audit(
            self.admin, "membership_updated", other, {"before": {"address": "Annan 3"}, "after": {"address": "Annan 4"}}
        )

        matrikel.anonymize_person(self.main, self.admin)

        self.assertEqual(
            db.MatrikelAudit.get_by_id(patched.id).payload,
            {
                "before": {"address": "[borttagen]", "city": "[borttagen]", "payment_note": "betalt 2025"},
                "after": {"address": "[borttagen]", "postal_address": "[borttagen]", "payment_note": "betalt 2026"},
            },
        )
        self.assertEqual(db.MatrikelAudit.get_by_id(elsewhere.id).payload["after"], {"address": "Annan 4"})

    def test_anonymize_scrubs_linked_application(self):
        """GDPR: the approved application row is a direct PII duplicate via
        the created_member FK — erasure must scrub it too."""
        app_row = db.MemberApplication.create(
            first_name="Frank",
            last_name="Familjesson",
            email="frank@example.com",
            phone="070-1234567",
            address="Storgatan 1",
            motivation="Vill vara med i föreningen",
            gdpr_consented_at=datetime.now(),
            status="approved",
            created_member=self.family,
        )
        matrikel.anonymize_person(self.family, self.admin)
        app_row = db.MemberApplication.get_by_id(app_row.id)
        self.assertEqual(app_row.first_name, "Borttagen")
        self.assertEqual(app_row.last_name, "person")
        self.assertEqual(app_row.email, "[borttagen]")
        self.assertIsNone(app_row.phone)
        self.assertIsNone(app_row.address)
        self.assertIsNone(app_row.motivation)
        # Review metadata and linkage stay for the audit trail.
        self.assertEqual(app_row.status, "approved")
        self.assertEqual(app_row.created_member_id, self.family.id)

    def test_anonymize_detaches_through_the_unlink_path(self):
        user = da.register_user("anon@example.com", "pass", username="anon")
        self.family.user = user
        self.family.save()
        matrikel.anonymize_person(self.family, self.admin)
        self.assertIsNone(db.Member.get_by_id(self.family.id).user_id)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_unlinked")
        self.assertEqual(audit.payload, {"person_id": self.family.id, "user_id": user.id, "source": "anonymize"})

    def test_create_membership_with_allocation(self):
        counter_before = db.MemberNumberCounter.select().first().value
        membership = matrikel.create_membership(
            {"first_name": "Ny", "last_name": "Medlem", "email": "ny@example.com", "allocate": True},
            self.admin,
        )
        self.assertEqual(membership.member_number, counter_before + 1)
        main = db.Member.get(db.Member.membership == membership, db.Member.role == "huvudmedlem")
        self.assertEqual(main.last_name, "Medlem")
        self.assertTrue(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "membership_created").exists())

    def test_create_membership_without_allocation_has_no_number(self):
        membership = matrikel.create_membership({"first_name": "Utan", "last_name": "Nummer"}, self.admin)
        self.assertIsNone(membership.member_number)

    def test_retire_membership_ends_persons_and_revokes_grants(self):
        grant = db.HerdAccessGrant.create(member=self.family, herd=self.herds[0], granted_by=self.admin)
        matrikel.retire_membership(self.membership, self.admin)
        self.assertEqual(db.Membership.get_by_id(self.membership.id).membership_status, "inactive")
        self.assertIsNotNone(db.Member.get_by_id(self.main.id).end_date)
        self.assertIsNotNone(db.Member.get_by_id(self.family.id).end_date)
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)
        self.assertTrue(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "membership_retired").exists())

    def test_add_person_to_inactive_membership_raises(self):
        matrikel.retire_membership(self.membership, self.admin)
        with self.assertRaises(ValueError):
            matrikel.add_person(
                self.membership,
                {"first_name": "Sen", "last_name": "Ankomst"},
                self.admin,
            )


class MatrikelAdminTestBase(DatabaseTest):
    """Shared fixture: membership with main + family person, matrikel_admin user."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.membership, self.main, self.family = _make_membership()
        self.matadmin = da.register_user("matadmin@example.com", "pass", username="matadmin")
        self.matadmin.add_role("matrikel_admin", None)

    def login(self, username="matadmin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def post_json(self, url, body):
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def patch_json(self, url, body):
        return self.client.patch(url, data=json.dumps(body), content_type="application/json")


class TestMembershipPatchEndpoint(MatrikelAdminTestBase):
    def patch_membership(self, body, membership_id=None):
        mid = membership_id if membership_id is not None else self.membership.id
        return self.patch_json(f"/api/v2/memberships/{mid}", body)

    def test_anonymous_401(self):
        self.assertEqual(self.patch_membership({"notes": "x"}).status_code, 401)

    def test_manager_403(self):
        self.login("man")
        self.assertEqual(self.patch_membership({"notes": "x"}).status_code, 403)

    def test_owner_403(self):
        self.login("owner")
        self.assertEqual(self.patch_membership({"notes": "x"}).status_code, 403)

    def test_admin_allowed(self):
        self.login("admin")
        self.assertEqual(self.patch_membership({"notes": "via admin"}).status_code, 200)

    def test_patch_status_friexemplar_and_audit(self):
        self.login()
        resp = self.patch_membership({"membership_status": "friexemplar"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Membership.get_by_id(self.membership.id).membership_status, "friexemplar")
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "membership_status_changed")
        self.assertEqual(audit.payload["before"]["membership_status"], "active")
        self.assertEqual(audit.payload["after"]["membership_status"], "friexemplar")

    def test_patch_invalid_status_400(self):
        self.login()
        self.assertEqual(self.patch_membership({"membership_status": "garbage"}).status_code, 400)

    def test_patch_membership_writes_only_changed_columns(self):
        """The membership lock stops a status flip from
        racing a link, but a full-row save() of the stale instance would still
        overwrite a flip committed before the lock was granted — restoring herd
        access to every linked huvudmedlem with no audit. The UPDATE must carry
        only the columns this body changed."""
        self.login()
        with patch.object(db.Membership, "save", autospec=True, side_effect=db.Membership.save) as spy:
            resp = self.patch_membership({"notes": "bara en anteckning"})
        self.assertEqual(resp.status_code, 200, resp.data)
        # Compare by field NAME: Field.__eq__ builds an Expression, so `in`/`not in`
        # on a list of Fields is meaningless (every membership test would pass).
        names = {f.name for f in spy.call_args.kwargs["only"]}
        self.assertIn("notes", names)
        self.assertIn("updated_at", names)
        self.assertNotIn("membership_status", names)
        self.assertEqual(db.Membership.get_by_id(self.membership.id).notes, "bara en anteckning")

    def test_patch_postal_address_alias_splits_and_canonicalizes(self):
        """Legacy single-column alias (migration 29 stores postal_code + city).
        The echoed postal_address is derived, so a compact code comes back
        canonical and a blank value comes back null."""
        self.login()
        for sent, stored, echoed in (
            ("62355 Visby", ("623 55", "Visby"), "623 55 Visby"),
            ("Box 12 Visby", (None, "Box 12 Visby"), "Box 12 Visby"),
            ("", (None, None), None),
            (None, (None, None), None),
        ):
            with self.subTest(sent=sent):
                resp = self.patch_membership({"postal_address": sent})
                self.assertEqual(resp.status_code, 200, resp.data)
                self.assertEqual(resp.get_json()["postal_address"], echoed)
                ms = db.Membership.get_by_id(self.membership.id)
                self.assertEqual((ms.postal_code, ms.city), stored)

    def test_patch_postal_address_non_string_400(self):
        self.login()
        resp = self.patch_membership({"postal_address": 12345})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.content_type, "application/problem+json")
        ms = db.Membership.get_by_id(self.membership.id)
        self.assertEqual((ms.postal_code, ms.city), (None, None))

    def test_patch_member_number_success(self):
        self.login()
        resp = self.patch_membership({"member_number": 500})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Membership.get_by_id(self.membership.id).member_number, 500)
        counter = db.MemberNumberCounter.select().first()
        self.assertIsNotNone(counter)
        self.assertGreaterEqual(counter.value, 500)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "member_number_changed")
        self.assertEqual(audit.payload["before"]["member_number"], 6)
        self.assertEqual(audit.payload["after"]["member_number"], 500)

    def test_patch_member_number_duplicate_409(self):
        db.Membership.create(member_number=7, membership_status="active")
        self.login()
        resp = self.patch_membership({"member_number": 7})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.content_type, "application/problem+json")

    def test_patch_member_number_clash_created_inside_the_transaction_409(self):
        """Two admins both pass the pre-transaction clash check. The
        counter row (raise_counter_to → FOR UPDATE) is what serialises every
        member_number writer, so the loser must re-run the clash query behind
        that lock and answer the same 409 — never a 500 from the unique index."""
        self.login()
        counter_before = db.MemberNumberCounter.select().first()
        value_before = counter_before.value if counter_before is not None else None
        original = matrikel.raise_counter_to

        def steal(value):
            original(value)  # raises the high-water mark to 500
            db.Membership.create(member_number=500, membership_status="active")

        with patch.object(memberships_routes, "raise_counter_to", steal):
            resp = self.patch_membership({"member_number": 500})
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(resp.get_json()["title"], "Medlemsnumret används redan")
        self.assertEqual(db.Membership.get_by_id(self.membership.id).member_number, 6)
        # The 409 is raised, not returned, so the whole transaction rolls back —
        # the counter must not keep a high-water mark for a number nobody got.
        counter_after = db.MemberNumberCounter.select().first()
        self.assertEqual(counter_after.value if counter_after is not None else None, value_before)

    def test_patch_member_number_unique_index_backstop_409(self):
        """The index is the backstop for the window between the re-check and the
        write: the IntegrityError must map to the same 409, not a 500."""
        self.login()
        original_save = db.Membership.save
        armed = [True]
        target_id = self.membership.id

        def save_after_clash(row, *args, **kwargs):
            if armed[0] and row.id == target_id:
                armed[0] = False
                # insert(), not create() — create() would recurse through save()
                db.Membership.insert(member_number=7, membership_status="active").execute()
            return original_save(row, *args, **kwargs)

        with patch.object(db.Membership, "save", save_after_clash):
            resp = self.patch_membership({"member_number": 7})
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(db.Membership.get_by_id(self.membership.id).member_number, 6)

    def test_patch_member_number_invalid_400(self):
        self.login()
        for bad in (0, -3, "abc"):
            resp = self.patch_membership({"member_number": bad})
            self.assertEqual(resp.status_code, 400, f"member_number={bad!r}")

    def test_patch_unknown_membership_404(self):
        self.login()
        self.assertEqual(self.patch_membership({"notes": "x"}, membership_id=99999).status_code, 404)


class TestMembershipCreateRetireEndpoints(MatrikelAdminTestBase):
    def test_create_anonymous_401(self):
        resp = self.post_json("/api/v2/memberships", {"first_name": "A", "last_name": "B"})
        self.assertEqual(resp.status_code, 401)

    def test_create_manager_403(self):
        self.login("man")
        resp = self.post_json("/api/v2/memberships", {"first_name": "A", "last_name": "B"})
        self.assertEqual(resp.status_code, 403)

    def test_create_allocates_and_returns_201(self):
        self.login()
        resp = self.post_json(
            "/api/v2/memberships",
            {"first_name": "Ny", "last_name": "Medlem", "email": "ny@example.com", "allocate": True},
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        data = resp.get_json()
        self.assertIsNotNone(data["member_number"])
        self.assertEqual(data["persons"][0]["last_name"], "Medlem")

    def test_create_missing_name_400(self):
        self.login()
        resp = self.post_json("/api/v2/memberships", {"email": "x@example.com"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.content_type, "application/problem+json")

    def test_retire_soft_deletes_and_returns_entity(self):
        self.login()
        resp = self.client.delete(f"/api/v2/memberships/{self.membership.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.get_json()["membership_status"], "inactive")
        self.assertIsNotNone(db.Member.get_by_id(self.main.id).end_date)

    def test_retire_manager_403(self):
        self.login("man")
        self.assertEqual(self.client.delete(f"/api/v2/memberships/{self.membership.id}").status_code, 403)

    def test_retire_unknown_404(self):
        self.login()
        self.assertEqual(self.client.delete("/api/v2/memberships/99999").status_code, 404)

    def test_create_with_structured_address(self):
        self.login()
        resp = self.post_json(
            "/api/v2/memberships",
            {
                "first_name": "Ny",
                "last_name": "Medlem",
                "address": "Gatan 3",
                "postal_code": "62355",
                "city": "Visby",
                "allocate": True,
            },
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        body = resp.get_json()
        self.assertEqual(
            (body["postal_code"], body["city"], body["postal_address"]), ("623 55", "Visby", "623 55 Visby")
        )

    def test_create_with_alias_and_both_layouts_400(self):
        self.login()
        resp = self.post_json(
            "/api/v2/memberships", {"first_name": "A", "last_name": "B", "postal_address": "623 55 Visby"}
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.get_json()["city"], "Visby")
        resp = self.post_json(
            "/api/v2/memberships",
            {"first_name": "A", "last_name": "B", "postal_address": "623 55 Visby", "postal_code": "623 55"},
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_create_with_overlong_non_parsing_alias_400(self):
        self.login()
        before = db.Membership.select().count()
        resp = self.post_json(
            "/api/v2/memberships", {"first_name": "A", "last_name": "B", "postal_address": "Box " + "x" * 100}
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["detail"], "Postort får vara högst 100 tecken")
        self.assertEqual(db.Membership.select().count(), before)

    def test_retire_response_carries_derived_postal_address(self):
        self.login()
        self.membership.postal_code, self.membership.city = "623 55", "Visby"
        self.membership.save()
        resp = self.client.delete(f"/api/v2/memberships/{self.membership.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.get_json()["postal_address"], "623 55 Visby")


class TestPersonMutationEndpoints(MatrikelAdminTestBase):
    def setUp(self):
        super().setUp()
        self.login()

    def add_person(self, body, membership_id=None):
        mid = membership_id if membership_id is not None else self.membership.id
        return self.post_json(f"/api/v2/memberships/{mid}/persons", body)

    def test_add_person_201(self):
        resp = self.add_person({"first_name": "Nina", "last_name": "Nysson", "email": "nina@example.com"})
        self.assertEqual(resp.status_code, 201, resp.data)
        data = resp.get_json()
        self.assertEqual(data["role"], "familjemedlem")
        self.assertFalse(data["duplicate_contact_email"])

    def test_add_person_duplicate_email_warns(self):
        resp = self.add_person({"first_name": "Nina", "last_name": "Nysson", "email": "frank@example.com"})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.get_json()["duplicate_contact_email"])

    def test_add_person_missing_name_400(self):
        self.assertEqual(self.add_person({"first_name": "Nina"}).status_code, 400)

    def test_add_person_non_string_field_400(self):
        # A JSON list/number/object for a string field must 400, not 500
        # (sol review finding 11).
        for bad in ([1, 2], 42, {"x": 1}):
            resp = self.add_person({"first_name": bad, "last_name": "Nysson"})
            self.assertEqual(resp.status_code, 400, f"first_name={bad!r}")
            self.assertEqual(resp.content_type, "application/problem+json")

    def test_add_person_to_inactive_membership_400(self):
        # add_person's FOR UPDATE guard rejects an inactive membership
        # (Gemini review — TOCTOU with retire_membership).
        matrikel.retire_membership(self.membership, self.admin)
        resp = self.add_person({"first_name": "Sen", "last_name": "Ankomst"})
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.content_type, "application/problem+json")

    def test_add_second_main_member_409(self):
        resp = self.add_person({"first_name": "Kupp", "last_name": "Makare", "role": "huvudmedlem"})
        self.assertEqual(resp.status_code, 409)

    def test_patch_person_contact_and_audit(self):
        resp = self.patch_json(f"/api/v2/persons/{self.family.id}", {"phone": "+46701234567"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Member.get_by_id(self.family.id).phone, "+46701234567")
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_updated")
        self.assertEqual(audit.payload["person_id"], self.family.id)
        self.assertEqual(audit.payload["after"]["phone"], "+46701234567")

    def test_patch_person_writes_only_changed_columns(self):
        """The route reads the person at request start
        and used to save every column — writing member.user_id back from that stale
        copy. A link committed in between would be silently NULLed, and an unlink
        would be resurrected (re-conveying the membership's herds, unconfirmed and
        unaudited). The UPDATE must carry only the columns this body changed."""
        account = da.register_user("konto@example.com", "pass", username="konto")
        matrikel.link_member_user(self.family.id, account.id, actor=self.admin, mode="admin")
        with patch.object(db.Member, "save", autospec=True, side_effect=db.Member.save) as spy:
            resp = self.patch_json(f"/api/v2/persons/{self.family.id}", {"phone": "+46701234567"})
        self.assertEqual(resp.status_code, 200, resp.data)
        # Compare by field NAME — see the note in test_patch_membership_writes_only_changed_columns.
        names = {f.name for f in spy.call_args.kwargs["only"]}
        self.assertIn("phone", names)
        self.assertIn("updated_at", names)
        self.assertNotIn("user", names)
        person = db.Member.get_by_id(self.family.id)
        self.assertEqual((person.phone, person.user_id), ("+46701234567", account.id))

    def test_patch_person_refuses_after_anonymization(self):
        """GDPR: the route reads the person at request start, so an
        anonymization committed in between would write the body's phone back onto
        the scrubbed row. The re-read under the membership lock must answer 409
        and leave the row scrubbed."""
        matrikel.anonymize_person(self.family, self.admin)
        resp = self.patch_json(f"/api/v2/persons/{self.family.id}", {"phone": "+46701234567", "notes": "x"})
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(resp.get_json()["title"], "Personen är anonymiserad")
        person = db.Member.get_by_id(self.family.id)
        self.assertIsNone(person.phone)
        self.assertIsNone(person.notes)
        self.assertEqual(
            (person.first_name, person.last_name),
            (matrikel.ANONYMIZED_FIRST_NAME, matrikel.ANONYMIZED_LAST_NAME),
        )

    def test_patch_person_ended_but_not_anonymized_still_editable(self):
        """Only GDPR erasure blocks the edit. A soft-deleted person keeps the
        behaviour it had before the fix wave (ADR-0006)."""
        matrikel.soft_delete_person(self.family, self.admin)
        self.assertIsNotNone(db.Member.get_by_id(self.family.id).end_date)
        resp = self.patch_json(f"/api/v2/persons/{self.family.id}", {"phone": "+46701234567"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Member.get_by_id(self.family.id).phone, "+46701234567")

    def test_patch_person_demote_active_main_409(self):
        resp = self.patch_json(f"/api/v2/persons/{self.main.id}", {"role": "familjemedlem"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(db.Member.get_by_id(self.main.id).role, "huvudmedlem")

    def test_patch_person_promote_second_main_409(self):
        resp = self.patch_json(f"/api/v2/persons/{self.family.id}", {"role": "huvudmedlem"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(db.Member.get_by_id(self.family.id).role, "familjemedlem")

    def test_delete_person_soft_and_revokes_grants(self):
        grant = db.HerdAccessGrant.create(member=self.family, herd=self.herds[0], granted_by=self.admin)
        resp = self.client.delete(f"/api/v2/persons/{self.family.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNotNone(db.Member.get_by_id(self.family.id).end_date)
        self.assertIsNotNone(db.HerdAccessGrant.get_by_id(grant.id).revoked_at)

    def test_delete_main_member_409(self):
        resp = self.client.delete(f"/api/v2/persons/{self.main.id}")
        self.assertEqual(resp.status_code, 409)
        self.assertIsNone(db.Member.get_by_id(self.main.id).end_date)

    def test_main_member_swap_endpoint(self):
        resp = self.post_json(
            f"/api/v2/memberships/{self.membership.id}/main-member",
            {"person_id": self.family.id},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Member.get_by_id(self.main.id).role, "familjemedlem")
        self.assertEqual(db.Member.get_by_id(self.family.id).role, "huvudmedlem")
        _other_membership, other_main, _other_family = _make_membership(number=8)
        resp = self.post_json(
            f"/api/v2/memberships/{self.membership.id}/main-member",
            {"person_id": other_main.id},
        )
        self.assertEqual(resp.status_code, 409)

    def test_anonymize_endpoint_redacts_prior_audits(self):
        resp = self.add_person({"first_name": "Nina", "last_name": "Nysson", "email": "nina@example.com"})
        person_id = resp.get_json()["id"]
        resp = self.client.post(f"/api/v2/persons/{person_id}/anonymize")
        self.assertEqual(resp.status_code, 200, resp.data)
        person = db.Member.get_by_id(person_id)
        self.assertEqual(person.first_name, "Borttagen")
        self.assertIsNone(person.email)
        added = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_added")
        self.assertEqual(added.payload["person_id"], person_id)
        self.assertEqual(added.payload["email"], "[borttagen]")
        self.assertTrue(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_anonymized").exists())
