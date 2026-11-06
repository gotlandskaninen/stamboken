"""Phase 19 — bounded races around link_member_user (PostgreSQL row locks)."""

import json
import threading
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import utils.data_access as da
import utils.database as db
import utils.matrikel as matrikel
from blueprints import members as members_routes
from blueprints import memberships as memberships_routes
from herdbook import APP
from utils.members import try_auto_link_member

from tests.database_test import _USE_POSTGRES
from tests.test_person_link_api import LinkApiBase


@unittest.skipUnless(_USE_POSTGRES, "FOR UPDATE serialisation needs PostgreSQL")
class TestLinkRaces(LinkApiBase):
    def _race(self, *workers):
        """Start the callables together (barrier); return the ConfirmRequired/LinkError
        instances they raised. Any other exception fails the test."""
        barrier = threading.Barrier(len(workers))
        outcomes, failures = [], []

        def run(fn):
            try:
                barrier.wait(timeout=10)
                fn()
            except (matrikel.ConfirmRequired, matrikel.LinkError) as exc:
                outcomes.append(exc)
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        threads = [threading.Thread(target=run, args=(fn,)) for fn in workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        return outcomes

    def _assert_no_silent_conveyance(self):
        for row in db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked"):
            self.assertEqual(row.payload["conveys_herd_ids"], [])

    def test_manual_link_vs_oauth_auto_link(self):
        # The OAuth path only fires for a @gotlandskaninen.se login (utils/members.py domain guard).
        workspace = da.register_user("erik@gotlandskaninen.se", "pass", username="erik.ws")
        other = db.Member.create(
            membership=self.ms,
            first_name="Erik",
            last_name="Ws",
            role="skotare",
            workspace_email="erik@gotlandskaninen.se",
        )
        family_id, other_id, user_id, admin_id = self.family.id, other.id, workspace.id, self.admin.id
        self._race(
            lambda: matrikel.link_member_user(family_id, user_id, actor=db.User.get_by_id(admin_id), mode="admin"),
            lambda: try_auto_link_member(db.Member.get_by_id(other_id), db.User.get_by_id(user_id)),
        )
        self.assertEqual(db.Member.select().where(db.Member.user == user_id).count(), 1)

    def test_manual_link_vs_cli_link(self):
        family_id, skotare_id, user_id, admin_id = self.family.id, self.skotare.id, self.account.id, self.admin.id
        outcomes = self._race(
            lambda: matrikel.link_member_user(family_id, user_id, actor=db.User.get_by_id(admin_id), mode="admin"),
            lambda: matrikel.link_member_user(skotare_id, user_id, actor=db.User.get_by_id(admin_id), mode="cli"),
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(db.Member.select().where(db.Member.user == user_id).count(), 1)

    def test_link_vs_anonymize(self):
        """One outcome — either the link lost (ended person) or anonymize
        detached it; never a linked ghost."""
        family_id, user_id, admin_id = self.family.id, self.account.id, self.admin.id
        self._race(
            lambda: matrikel.link_member_user(family_id, user_id, actor=db.User.get_by_id(admin_id), mode="admin"),
            lambda: matrikel.anonymize_person(db.Member.get_by_id(family_id), db.User.get_by_id(admin_id)),
        )
        self.assertIsNone(db.Member.get_by_id(family_id).user_id)
        self.assertFalse(db.Member.select().where(db.Member.user == user_id).exists())

    def test_unlink_vs_anonymize(self):
        matrikel.link_member_user(self.family.id, self.account.id, actor=db.User.get_by_id(self.admin.id), mode="admin")
        family_id, admin_id = self.family.id, self.admin.id
        self._race(
            lambda: matrikel.unlink_member_user(family_id, actor=db.User.get_by_id(admin_id)),
            lambda: matrikel.anonymize_person(db.Member.get_by_id(family_id), db.User.get_by_id(admin_id)),
        )
        self.assertIsNone(db.Member.get_by_id(family_id).user_id)
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_unlinked").count(), 1)

    def test_link_vs_main_member_swap(self):
        family_id, user_id, admin_id, ms_id = self.family.id, self.account.id, self.admin.id, self.ms.id
        self._race(
            lambda: matrikel.link_member_user(
                family_id, user_id, actor=db.User.get_by_id(admin_id), mode="admin", confirmed_herd_ids=[]
            ),
            lambda: matrikel.swap_main_member(
                db.Membership.get_by_id(ms_id), db.Member.get_by_id(family_id), db.User.get_by_id(admin_id)
            ),
        )
        self._assert_no_silent_conveyance()

    def test_link_vs_grant_creation(self):
        family_id, user_id, admin_id, herd_id = self.family.id, self.account.id, self.admin.id, self.herds[1].id
        self._race(
            lambda: matrikel.link_member_user(
                family_id, user_id, actor=db.User.get_by_id(admin_id), mode="admin", confirmed_herd_ids=[]
            ),
            lambda: matrikel.create_grant(
                db.Member.get_by_id(family_id), db.Herd.get_by_id(herd_id), None, db.User.get_by_id(admin_id)
            ),
        )
        self._assert_no_silent_conveyance()

    def test_link_vs_grant_renewal(self):
        """renew_grant() must wait for the link's membership lock: an EXPIRED grant contributes nothing to the delta,
        so a renewal that slipped in between the delta read and the commit
        would hand the freshly linked account the herd with no confirmation."""
        family_id, user_id, admin_id = self.family.id, self.account.id, self.admin.id
        expired = db.HerdAccessGrant.create(
            member=self.family, herd=self.herds[0], granted_by=self.admin, valid_until=date.today() - timedelta(days=1)
        )
        entered, release, renew_done = threading.Event(), threading.Event(), threading.Event()
        original_delta = matrikel.link_access_delta
        failures = []

        def paused_delta(person, user):
            entered.set()
            assert release.wait(timeout=10), "the test never released the paused link"
            return original_delta(person, user)

        def link():
            try:
                matrikel.link_member_user(
                    family_id, user_id, actor=db.User.get_by_id(admin_id), mode="admin", confirmed_herd_ids=[]
                )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        def renew():
            try:
                matrikel.renew_grant(db.HerdAccessGrant.get_by_id(expired.id), db.User.get_by_id(admin_id))
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                renew_done.set()
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        with patch.object(matrikel, "link_access_delta", paused_delta):
            link_thread = threading.Thread(target=link)
            link_thread.start()
            self.assertTrue(entered.wait(timeout=10), "link never reached link_access_delta")
            renew_thread = threading.Thread(target=renew)
            renew_thread.start()
            self.assertFalse(
                renew_done.wait(timeout=1.5), "renew_grant finished while the link still held the membership lock"
            )
            release.set()
            link_thread.join(timeout=15)
            renew_thread.join(timeout=15)
        for thread in (link_thread, renew_thread):
            self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        # The link read an empty delta (grant expired) and committed first; the
        # renewal queued behind the lock and is an ordinary audited grant action.
        self.assertEqual(db.Member.get_by_id(family_id).user_id, user_id)
        self.assertGreater(db.HerdAccessGrant.get_by_id(expired.id).valid_until, date.today())
        self._assert_no_silent_conveyance()

    def test_link_vs_membership_status_flip(self):
        """The PRODUCTION status writer must wait for the link's membership lock.
        A plain barrier race cannot prove that — either order is
        a valid outcome — so the link is PAUSED inside its transaction, after
        the membership row is locked, and the route must not finish until the
        link is released. A route without FOR UPDATE would
        answer 200 while the link still holds the lock and fail this test."""
        self.ms.membership_status = "pending"
        self.ms.save()
        main_id, user_id, admin_id, ms_id = self.main.id, self.account.id, self.admin.id, self.ms.id
        entered, release, patch_done = threading.Event(), threading.Event(), threading.Event()
        original_delta = matrikel.link_access_delta
        failures = []

        def paused_delta(person, user):
            # link_member_user calls this AFTER _lock_for_link — locks are held here.
            entered.set()
            assert release.wait(timeout=10), "the test never released the paused link"
            return original_delta(person, user)

        def link():
            try:
                matrikel.link_member_user(
                    main_id, user_id, actor=db.User.get_by_id(admin_id), mode="admin", confirmed_herd_ids=[]
                )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        def activate():
            try:
                client = APP.test_client()
                client.post("/api/login", json={"username": "matrikel", "password": "pass"})
                resp = client.patch(
                    f"/api/v2/memberships/{ms_id}",
                    data=json.dumps({"membership_status": "active"}),
                    content_type="application/json",
                )
                assert resp.status_code == 200, resp.data
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                patch_done.set()

        with patch.object(matrikel, "link_access_delta", paused_delta):
            link_thread = threading.Thread(target=link)
            link_thread.start()
            self.assertTrue(entered.wait(timeout=10), "link never reached link_access_delta")
            patch_thread = threading.Thread(target=activate)
            patch_thread.start()
            self.assertFalse(
                patch_done.wait(timeout=1.5), "status PATCH finished while the link still held the membership lock"
            )
            release.set()
            link_thread.join(timeout=15)
            patch_thread.join(timeout=15)
        for thread in (link_thread, patch_thread):
            self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        self.assertEqual(db.Membership.get_by_id(ms_id).membership_status, "active")
        # Linked while still pending → empty delta, no confirmation needed; the
        # activation that queued behind the lock conveys nothing retroactively.
        self.assertEqual(db.Member.get_by_id(main_id).user_id, user_id)
        self._assert_no_silent_conveyance()

    def test_consent_patch_vs_consent_patch(self):
        """GDPR: two tabs, two switches. The withdrawal commits
        while the other tab still holds its pre-withdrawal read — without the
        membership lock and the partial merge the second save replays the whole
        blob and re-enables the withdrawn e-post consent, which the Koharen
        export then prints."""
        user = da.register_user("tabs@example.com", "pass", username="tabs")
        ms = db.Membership.create(member_number=42, membership_status="active", publication_consent={"email": True})
        db.Member.create(membership=ms, first_name="Tva", last_name="Flikar", role="huvudmedlem", user=user)
        ms_id = ms.id

        def logged_in_client():
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "tabs", "password": "pass"})
            return client

        withdraw_client, other_client = logged_in_client(), logged_in_client()
        entered, release, other_done = threading.Event(), threading.Event(), threading.Event()
        original_save = db.Membership.save
        failures, responses = [], {}

        def paused_save(row, *args, **kwargs):
            # Pause the withdrawal INSIDE its transaction, with the membership
            # row already locked — the second tab must queue behind it.
            if row.id == ms_id and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused withdrawal"
            return original_save(row, *args, **kwargs)

        def consent_patch(client, body, key):
            try:
                responses[key] = client.patch(
                    "/api/v2/members/me/consent", data=json.dumps(body), content_type="application/json"
                )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                if key == "other":
                    other_done.set()

        with patch.object(db.Membership, "save", paused_save):
            withdraw = threading.Thread(target=consent_patch, args=(withdraw_client, {"email": False}, "withdraw"))
            withdraw.start()
            self.assertTrue(entered.wait(timeout=10), "the withdrawal never reached its save")
            other = threading.Thread(target=consent_patch, args=(other_client, {"name": True}, "other"))
            other.start()
            self.assertFalse(
                other_done.wait(1.5),
                "the second consent PATCH finished while the withdrawal still held the membership lock",
            )
            release.set()
            withdraw.join(timeout=15)
            other.join(timeout=15)
        for thread in (withdraw, other):
            self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        self.assertEqual(responses["withdraw"].status_code, 200, responses["withdraw"].data)
        self.assertEqual(responses["other"].status_code, 200, responses["other"].data)
        self.assertEqual(db.Membership.get_by_id(ms_id).publication_consent, {"email": False, "name": True})

    def _stale_status_patch_race(self, url: str):
        """Two matrikel admins, two tabs, both showing `active`.
        Tab A deactivates and is paused inside its transaction with the
        membership row locked; tab B — still carrying its request-start read of
        `active` — re-submits `active` and queues behind the lock. Decided from
        the pre-lock read, B looks like "no change": /v2/members would still
        UPDATE the stale value back (herd access restored, no audit) and
        /v2/memberships would echo a stale `active` it never wrote. Decided
        from the locked row, B is a real inactive → active change: written,
        audited and returned as such."""
        ms_id = self.ms.id

        def logged_in_client():
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "matrikel", "password": "pass"})
            return client

        a_client, b_client = logged_in_client(), logged_in_client()
        entered, release, b_done = threading.Event(), threading.Event(), threading.Event()
        original_save = db.Membership.save
        failures, responses = [], {}

        def paused_save(row, *args, **kwargs):
            if row.id == ms_id and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused deactivation"
            return original_save(row, *args, **kwargs)

        def status_patch(client, status, key):
            try:
                responses[key] = client.patch(
                    url, data=json.dumps({"membership_status": status}), content_type="application/json"
                )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                if key == "b":
                    b_done.set()

        with patch.object(db.Membership, "save", paused_save):
            a = threading.Thread(target=status_patch, args=(a_client, "inactive", "a"))
            a.start()
            self.assertTrue(entered.wait(timeout=10), "the deactivation never reached its save")
            b = threading.Thread(target=status_patch, args=(b_client, "active", "b"))
            b.start()
            self.assertFalse(
                b_done.wait(1.5), "the stale PATCH finished while the deactivation still held the membership lock"
            )
            release.set()
            a.join(timeout=15)
            b.join(timeout=15)
        for thread in (a, b):
            self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        self.assertEqual(responses["a"].status_code, 200, responses["a"].data)
        self.assertEqual(responses["b"].status_code, 200, responses["b"].data)
        self.assertEqual(responses["b"].get_json()["membership_status"], "active")
        self.assertEqual(db.Membership.get_by_id(ms_id).membership_status, "active")
        audits = (
            db.MatrikelAudit.select()
            .where(db.MatrikelAudit.action == "membership_status_changed", db.MatrikelAudit.membership == ms_id)
            .order_by(db.MatrikelAudit.id)
        )
        self.assertEqual(
            [(row.payload["before"]["membership_status"], row.payload["after"]["membership_status"]) for row in audits],
            [("active", "inactive"), ("inactive", "active")],
        )

    def test_stale_status_patch_v2_members(self):
        self._stale_status_patch_race(f"/api/v2/members/{self.ms.id}")

    def test_stale_status_patch_v2_memberships(self):
        self._stale_status_patch_race(f"/api/v2/memberships/{self.ms.id}")

    def test_contact_patch_vs_anonymize(self):
        """GDPR: the self-service PATCH is paused after its
        request-start read, anonymize_person() runs to completion, and the
        released PATCH must answer 409 instead of writing its body's PII back
        onto the scrubbed row."""
        user = da.register_user("selfservice@example.com", "pass", username="selfservice")
        ms = db.Membership.create(member_number=43, membership_status="active", address="Gata 43")
        person = db.Member.create(
            membership=ms, first_name="Sig", last_name="Sjalv", role="huvudmedlem", user=user, phone="070-0"
        )
        person_id, admin_id, ms_id = person.id, self.admin.id, ms.id

        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "selfservice", "password": "pass"})
        entered, release = threading.Event(), threading.Event()
        original_read = members_routes._member_for_current_user
        failures, responses = [], []

        def paused_read():
            row = original_read()
            entered.set()
            assert release.wait(timeout=10), "the test never released the paused PATCH"
            return row

        def do_patch():
            try:
                responses.append(
                    client.patch(
                        "/api/v2/members/me/contact",
                        data=json.dumps({"phone": "+46701234567", "address": "Box 43"}),
                        content_type="application/json",
                    )
                )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)

        with patch.object(members_routes, "_member_for_current_user", paused_read):
            thread = threading.Thread(target=do_patch)
            thread.start()
            self.assertTrue(entered.wait(timeout=10), "the PATCH never reached its request-start read")
            matrikel.anonymize_person(db.Member.get_by_id(person_id), db.User.get_by_id(admin_id))
            release.set()
            thread.join(timeout=15)
        self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        self.assertEqual(responses[0].status_code, 409, responses[0].data)
        scrubbed = db.Member.get_by_id(person_id)
        self.assertIsNone(scrubbed.phone)
        self.assertEqual(
            (scrubbed.first_name, scrubbed.last_name), (matrikel.ANONYMIZED_FIRST_NAME, matrikel.ANONYMIZED_LAST_NAME)
        )
        # The sole person's erasure cleared the household address, and the
        # paused PATCH ("Box 43") must not have written it back.
        self.assertIsNone(db.Membership.get_by_id(ms_id).address)

    def test_person_patch_vs_anonymize(self):
        """Same race on the matrikel-admin route: paused after its request-start
        read, the PATCH must find the ended row under the membership lock and
        answer 409 rather than resurrect the person's phone."""
        person_id, admin_id = self.family.id, self.admin.id
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "matrikel", "password": "pass"})
        entered, release = threading.Event(), threading.Event()
        original_lookup = db.Member.get_or_none
        failures, responses = [], []

        def paused_lookup(*args, **kwargs):
            row = original_lookup(*args, **kwargs)
            if row is not None and row.id == person_id and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused PATCH"
            return row

        def do_patch():
            try:
                responses.append(
                    client.patch(
                        f"/api/v2/persons/{person_id}",
                        data=json.dumps({"phone": "+46701234567"}),
                        content_type="application/json",
                    )
                )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)

        with patch.object(db.Member, "get_or_none", paused_lookup):
            thread = threading.Thread(target=do_patch)
            thread.start()
            self.assertTrue(entered.wait(timeout=10), "the PATCH never reached its request-start read")
            matrikel.anonymize_person(db.Member.get_by_id(person_id), db.User.get_by_id(admin_id))
            release.set()
            thread.join(timeout=15)
        self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        self.assertEqual(responses[0].status_code, 409, responses[0].data)
        scrubbed = db.Member.get_by_id(person_id)
        self.assertIsNone(scrubbed.phone)
        self.assertEqual(
            (scrubbed.first_name, scrubbed.last_name), (matrikel.ANONYMIZED_FIRST_NAME, matrikel.ANONYMIZED_LAST_NAME)
        )

    # The window between a route's request-start read and the membership lock.
    # The request is PAUSED there, the competing writer runs to completion on
    # the main thread (it holds no locks the pause could block on), and the
    # released request must re-decide on the row it finds under the lock.

    def _selfservice_fixture(self, number, username):
        """Active membership, a linked huvudmedlem and a familjemedlem to promote."""
        user = da.register_user(f"{username}@example.com", "pass", username=username)
        ms = db.Membership.create(member_number=number, membership_status="active", address=f"Gata {number}")
        person = db.Member.create(
            membership=ms, first_name="Sig", last_name="Sjalv", role="huvudmedlem", user=user, phone="070-0"
        )
        other = db.Member.create(membership=ms, first_name="Ny", last_name="Huvud", role="familjemedlem")
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": username, "password": "pass"})
        return ms, person, other, client

    def _paused_selfservice_patch(self, client, path, body, competitor):
        entered, release = threading.Event(), threading.Event()
        original_read = members_routes._member_for_current_user
        failures, responses = [], []

        def paused_read():
            row = original_read()
            entered.set()
            assert release.wait(timeout=10), "the test never released the paused PATCH"
            return row

        def do_patch():
            try:
                responses.append(client.patch(path, data=json.dumps(body), content_type="application/json"))
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)

        with patch.object(members_routes, "_member_for_current_user", paused_read):
            thread = threading.Thread(target=do_patch)
            thread.start()
            self.assertTrue(entered.wait(timeout=10), "the PATCH never reached its request-start read")
            competitor()
            release.set()
            thread.join(timeout=15)
        self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        return responses[0]

    def _assert_selfservice_untouched(self, ms_id, person_id, number):
        person, ms = db.Member.get_by_id(person_id), db.Membership.get_by_id(ms_id)
        self.assertEqual(person.phone, "070-0")
        self.assertEqual(ms.address, f"Gata {number}")
        self.assertEqual(ms.publication_consent, {})

    def _swap_competitor(self, ms_id, other_id):
        admin_id = self.admin.id
        return lambda: matrikel.swap_main_member(
            db.Membership.get_by_id(ms_id), db.Member.get_by_id(other_id), db.User.get_by_id(admin_id)
        )

    def _unlink_competitor(self, person_id):
        admin_id = self.admin.id
        return lambda: matrikel.unlink_member_user(person_id, actor=db.User.get_by_id(admin_id))

    def _anonymize_competitor(self, person_id):
        admin_id = self.admin.id
        return lambda: matrikel.anonymize_person(db.Member.get_by_id(person_id), db.User.get_by_id(admin_id))

    def test_contact_patch_vs_main_member_swap(self):
        """A demotion that commits in the window must cost the PATCH its 403 —
        the pre-lock role gate saw a huvudmedlem that no longer exists."""
        ms, person, other, client = self._selfservice_fixture(51, "swapcontact")
        resp = self._paused_selfservice_patch(
            client,
            "/api/v2/members/me/contact",
            {"phone": "+46701234567", "address": "Box 51"},
            self._swap_competitor(ms.id, other.id),
        )
        self.assertEqual(resp.status_code, 403, resp.data)
        self._assert_selfservice_untouched(ms.id, person.id, 51)

    def test_contact_patch_vs_unlink(self):
        ms, person, _other, client = self._selfservice_fixture(52, "unlinkcontact")
        resp = self._paused_selfservice_patch(
            client,
            "/api/v2/members/me/contact",
            {"phone": "+46701234567", "address": "Box 52"},
            self._unlink_competitor(person.id),
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self._assert_selfservice_untouched(ms.id, person.id, 52)

    def test_consent_patch_vs_main_member_swap(self):
        ms, person, other, client = self._selfservice_fixture(53, "swapconsent")
        resp = self._paused_selfservice_patch(
            client, "/api/v2/members/me/consent", {"email": True}, self._swap_competitor(ms.id, other.id)
        )
        self.assertEqual(resp.status_code, 403, resp.data)
        self._assert_selfservice_untouched(ms.id, person.id, 53)

    def test_consent_patch_vs_unlink(self):
        ms, person, _other, client = self._selfservice_fixture(54, "unlinkconsent")
        resp = self._paused_selfservice_patch(
            client, "/api/v2/members/me/consent", {"email": True}, self._unlink_competitor(person.id)
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self._assert_selfservice_untouched(ms.id, person.id, 54)

    def test_consent_patch_vs_anonymize(self):
        """GDPR: a consent written after the erasure would be printed in the
        Koharen export for a person who exercised the right to be forgotten."""
        ms, person, _other, client = self._selfservice_fixture(55, "anonconsent")
        resp = self._paused_selfservice_patch(
            client, "/api/v2/members/me/consent", {"email": True}, self._anonymize_competitor(person.id)
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(db.Membership.get_by_id(ms.id).publication_consent, {})
        self.assertIsNone(db.Member.get_by_id(person.id).user_id)

    def _my_membership_client(self):
        """Log in as the account linked to this membership's huvudmedlem."""
        matrikel.link_member_user(
            self.main.id,
            self.account.id,
            actor=db.User.get_by_id(self.admin.id),
            mode="admin",
            confirmed_herd_ids=[self.herds[0].id],
        )
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "erik.lindqvist", "password": "pass"})
        return client

    def _paused_my_membership_post(self, client, path, body, competitor):
        entered, release = threading.Event(), threading.Event()
        original_resolve = memberships_routes.resolve_own_membership
        failures, responses = [], []

        def paused_resolve(user):
            # Called inside the route's open transaction, before it takes any
            # row lock — the competitor can commit while we sit here.
            row = original_resolve(user)
            entered.set()
            assert release.wait(timeout=10), "the test never released the paused request"
            return row

        def do_post():
            try:
                responses.append(client.post(path, data=json.dumps(body), content_type="application/json"))
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)

        with patch.object(memberships_routes, "resolve_own_membership", paused_resolve):
            thread = threading.Thread(target=do_post)
            thread.start()
            self.assertTrue(entered.wait(timeout=10), "the request never reached resolve_own_membership")
            competitor()
            release.set()
            thread.join(timeout=15)
        self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        return responses[0]

    def test_my_membership_add_person_vs_unlink(self):
        client = self._my_membership_client()
        ms_id, before = self.ms.id, db.Member.select().where(db.Member.membership == self.ms).count()
        resp = self._paused_my_membership_post(
            client,
            "/api/v2/my-membership/persons",
            {"first_name": "Ny", "last_name": "Person", "role": "familjemedlem"},
            self._unlink_competitor(self.main.id),
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(db.Member.select().where(db.Member.membership == ms_id).count(), before)

    def test_my_membership_create_grant_vs_unlink(self):
        client = self._my_membership_client()
        family_id = self.family.id
        resp = self._paused_my_membership_post(
            client,
            f"/api/v2/my-membership/persons/{family_id}/grants",
            {"herd_id": self.herds[0].id},
            self._unlink_competitor(self.main.id),
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertFalse(db.HerdAccessGrant.select().where(db.HerdAccessGrant.member == family_id).exists())
