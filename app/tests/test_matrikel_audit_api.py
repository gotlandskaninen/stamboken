"""GET /api/v2/members/audit — the matrikel's change log (#244)."""

import json
import threading
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import utils.data_access as da
import utils.database as db
import utils.matrikel as matrikel

from tests.test_member_api import MatrikelApiTest, _mk_membership, _mk_person

URL = "/api/v2/members/audit"


class TestMatrikelAudit(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        self.ms = _mk_membership(number=41, address="Gata 1")
        self.person = _mk_person(self.ms, "Tova", "Testsson", "tova@example.com", phone="0701111111")
        self.other_ms = _mk_membership(number=42)
        _mk_person(self.other_ms, "Ulf", "Provsson", "ulf@example.com")

    def get(self, query=""):
        return self.client.get(f"{URL}?{query}")

    def patch_person(self, body):
        resp = self.client.patch(
            f"/api/v2/persons/{self.person.id}", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_email_change_shows_actor_and_time(self):
        self.login("matrikel")
        self.patch_person({"email": "tova.ny@example.com"})
        resp = self.get(f"membership_id={self.ms.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        row = resp.get_json()["rows"][0]
        self.assertEqual(row["action"], "person_updated")
        self.assertEqual(row["actor"], {"id": self.matrikel_user.id, "name": "matrikel"})
        self.assertEqual(row["membership"], {"id": self.ms.id, "member_number": 41})
        self.assertEqual(row["person"], {"id": self.person.id, "name": "Tova Testsson"})
        self.assertEqual(row["payload"]["before"], {"email": "tova@example.com"})
        self.assertEqual(row["payload"]["after"], {"email": "tova.ny@example.com"})
        created = datetime.fromisoformat(row["created_at"])
        self.assertIsNotNone(created.tzinfo)  # the browser must not guess the server's time zone
        self.assertLess(abs(created.astimezone() - datetime.now().astimezone()), timedelta(minutes=5))

    def test_access_per_role(self):
        matrikel.write_matrikel_audit(self.admin, "membership_updated", self.ms, {"before": {}, "after": {}})
        for username, status in (("admin", 200), ("matrikel", 200), ("man", 200), ("spec", 403), ("owner", 403)):
            with self.subTest(username=username):
                self.client.get("/api/logout")
                self.login(username)
                resp = self.get()
                self.assertEqual(resp.status_code, status, resp.data)
                if status == 403:
                    self.assertNotIn(b"rows", resp.data)
        self.client.get("/api/logout")
        self.assertEqual(self.get().status_code, 401)

    def test_manager_sees_what_the_member_page_shows_them(self):
        """Organisation number and a person's notes are not in GET /v2/members/<id> for a manager."""
        matrikel.write_matrikel_audit(
            self.admin,
            "membership_updated",
            self.ms,
            {"before": {"organization_number": "5560000000", "notes": "hushallsnot"}, "after": {"notes": "ny not"}},
        )
        matrikel.write_matrikel_audit(
            self.admin,
            "person_updated",
            self.ms,
            {"person_id": self.person.id, "before": {"notes": "personnot"}, "after": {"notes": "ny personnot"}},
        )
        self.login("man")
        text = self.get().get_data(as_text=True)
        for hidden in ("5560000000", "personnot"):
            self.assertNotIn(hidden, text)
        self.assertIn("hushallsnot", text)  # the membership's notes are in the manager's GET
        self.client.get("/api/logout")
        self.login("matrikel")
        text = self.get().get_data(as_text=True)
        for shown in ("5560000000", "personnot", "hushallsnot"):
            self.assertIn(shown, text)

    def test_anonymised_person_is_masked(self):
        self.login("matrikel")
        self.patch_person({"phone": "0702222222", "notes": "hemlig not"})
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        resp = self.get(f"membership_id={self.ms.id}")
        text = resp.get_data(as_text=True)
        for erased in ("Tova", "Testsson", "tova@example.com", "0701111111", "0702222222", "hemlig not"):
            self.assertNotIn(erased, text)
        rows = resp.get_json()["rows"]
        self.assertEqual(rows[0]["action"], "person_anonymized")
        updated = next(r for r in rows if r["action"] == "person_updated")
        self.assertEqual(updated["payload"]["after"]["phone"], matrikel.REDACTED_VALUE)

    def test_stored_payload_that_escaped_erasure_is_masked_on_read(self):
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        # as if written after the erasure, or by a path the erasure missed
        matrikel.write_matrikel_audit(
            self.admin, "person_updated", self.ms, {"person_id": self.person.id, "after": {"email": "kvar@example.com"}}
        )
        self.login()
        text = self.get().get_data(as_text=True)
        self.assertNotIn("kvar@example.com", text)

    def test_nightly_rows_without_actor_are_listed(self):
        matrikel.write_matrikel_audit(None, "person_anonymized", self.ms, {"person_id": self.person.id})
        self.login()
        rows = self.get().get_json()["rows"]
        self.assertEqual([(r["action"], r["actor"]) for r in rows], [("person_anonymized", None)])

    def test_filters_and_paging(self):
        old = matrikel.write_matrikel_audit(self.admin, "membership_updated", self.ms, {"before": {}, "after": {}})
        db.MatrikelAudit.update(created_at=datetime(2025, 1, 10, 12)).where(db.MatrikelAudit.id == old.id).execute()
        matrikel.write_matrikel_audit(self.matrikel_user, "person_removed", self.ms, {"person_id": self.person.id})
        matrikel.write_matrikel_audit(self.admin, "membership_retired", self.other_ms, {"ended_person_ids": []})
        self.login()

        def actions(query):
            resp = self.get(query)
            self.assertEqual(resp.status_code, 200, resp.data)
            return [r["action"] for r in resp.get_json()["rows"]]

        self.assertEqual(actions(f"membership_id={self.ms.id}"), ["person_removed", "membership_updated"])
        self.assertEqual(actions("member_number=41"), ["person_removed", "membership_updated"])
        self.assertEqual(actions("member_number=42"), ["membership_retired"])
        self.assertEqual(actions(f"member_number=41&membership_id={self.other_ms.id}"), [])
        self.assertEqual(actions("action=membership_retired"), ["membership_retired"])
        self.assertEqual(actions("actor=matrikel"), ["person_removed"])
        self.assertEqual(actions("actor=MATRIKEL"), ["person_removed"])  # Opus #248: case does not matter
        self.assertEqual(actions("to=2025-01-10"), ["membership_updated"])  # the whole day
        today = date.today().isoformat()
        self.assertEqual(actions(f"from={today}&to={today}"), ["membership_retired", "person_removed"])
        self.assertEqual(len(actions("from=0001-01-01&to=9999-12-31")), 3)  # Opus #248: no OverflowError
        page = self.get("per_page=1&page=2").get_json()
        self.assertEqual((page["total"], page["page"], page["per_page"]), (3, 2, 1))
        self.assertEqual([r["action"] for r in page["rows"]], ["person_removed"])
        self.assertEqual(self.get("per_page=999").get_json()["per_page"], 200)
        bad_ids = ("membership_id=0", "membership_id=-1", "member_number=0", "member_number=-5", "member_number=1.5")
        for bad in ("from=igar", "page=x", "membership_id=y", "member_number=z", *bad_ids):
            with self.subTest(bad=bad):
                self.assertEqual(self.get(bad).status_code, 400)

    def test_anonymised_persons_former_account_is_not_named(self):
        """Codex #248: a profile change logs her own account as actor; unlinked before erasure it keeps its name."""
        account = da.register_user("tova-konto@example.com", "pass")
        matrikel.link_member_user(self.person.id, account.id, actor=self.matrikel_user, mode="admin")
        matrikel.write_matrikel_audit(
            account, "kontakt_andrad", self.ms, {"person_id": self.person.id, "fields": ["phone"], "source": "profil"}
        )
        matrikel.unlink_member_user(self.person.id, actor=self.matrikel_user)
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        self.login("man")
        data = self.get(f"membership_id={self.ms.id}").get_json()
        text = json.dumps(data)
        self.assertNotIn("tova-konto", text)
        by_action = {r["action"]: r for r in data["rows"]}
        self.assertEqual(by_action["kontakt_andrad"]["actor"], {"id": None, "name": matrikel.REDACTED_VALUE})
        for action in ("person_user_linked", "person_user_unlinked"):
            self.assertEqual(by_action[action]["payload"]["user_id"], matrikel.REDACTED_VALUE)
            # the handler who linked and unlinked keeps the attribution
            self.assertEqual(by_action[action]["actor"]["id"], self.matrikel_user.id)
        for actor in ("tova-konto@example.com", "TOVA-KONTO@example.com"):
            with self.subTest(actor=actor):
                found = self.get(f"actor={actor}").get_json()
                self.assertEqual((found["total"], found["rows"]), (0, []))

    def _billing_row(self, minutes_before_now=0):
        """A membership_updated row with the household's old billing address, written now and dated back if asked:
        after the erasure, so the erasure's own redaction in the database never reached it."""
        row = matrikel.write_matrikel_audit(
            self.admin,
            "membership_updated",
            self.ms,
            {"before": {"billing_address": "Fakturagatan 9"}, "after": {"billing_address": None}},
        )
        at = datetime.now() - timedelta(minutes=minutes_before_now)
        db.MatrikelAudit.update(created_at=at).where(db.MatrikelAudit.id == row.id).execute()

    def _billing_shown(self):
        resp = self.get(f"membership_id={self.ms.id}&action=membership_updated")
        return "Fakturagatan" in resp.get_data(as_text=True), resp.get_json()["rows"]

    def test_erased_household_is_masked_on_read(self):
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)  # the only active person
        self._billing_row(minutes_before_now=5)  # dated before the erasure, as if the erasure had missed it
        self.login("man")
        shown, rows = self._billing_shown()
        self.assertFalse(shown)
        self.assertEqual(rows[0]["payload"]["before"]["billing_address"], matrikel.REDACTED_VALUE)

    def test_erased_household_masks_every_household_value_for_good(self):
        """Codex #248 r2–r5: once erased, the membership's household values are masked in all its rows, for every
        role. Also the new household's: the price of a rule that cannot leak across fields or back through the
        erasure's own placeholders. The keys stay, so the change shows."""
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        writes = (
            {"before": {"billing_address": None}, "after": {"billing_address": "Fakturagatan 9"}},  # written back
            {"before": {"notes": "[borttagen]"}, "after": {"notes": "gammal not"}},
        )
        for payload in writes:
            matrikel.write_matrikel_audit(self.admin, "membership_updated", self.ms, payload)
        _mk_person(self.ms, "Nils", "Nyman", "nils@example.com")
        later = (
            {"before": {"address": "Fakturagatan 9"}, "after": {"address": "Nya vägen 2"}},  # across fields
            {"before": {"notes": "gammal not"}, "after": {"notes": "ny not"}},
        )
        for payload in later:
            matrikel.write_matrikel_audit(self.admin, "membership_updated", self.ms, payload)
        for username in ("man", "admin"):
            with self.subTest(username=username):
                self.client.get("/api/logout")
                self.login(username)
                resp = self.get(f"membership_id={self.ms.id}&action=membership_updated")
                text = resp.get_data(as_text=True)
                for value in ("Fakturagatan", "gammal not", "Nya v", "ny not"):
                    self.assertNotIn(value, text)
                newest = resp.get_json()["rows"][0]["payload"]
                masked = matrikel.REDACTED_VALUE
                self.assertEqual(newest, {"before": {"notes": masked}, "after": {"notes": masked}})

    def test_household_with_an_active_person_is_not_masked(self):
        self._billing_row(minutes_before_now=5)
        _mk_person(self.ms, "Vera", "Testsson", role="familjemedlem")
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        self.login("man")
        self.assertIn("Fakturagatan 9", self.get(f"membership_id={self.ms.id}").get_data(as_text=True))

    def test_days_are_swedish_days(self):
        """Opus #248: Från/Till cut at midnight in Sweden, as the page shows the times, whatever the server's zone."""
        row = matrikel.write_matrikel_audit(self.admin, "membership_updated", self.ms, {"before": {}, "after": {}})
        sweden = datetime(2025, 1, 10, 0, 30, tzinfo=ZoneInfo("Europe/Stockholm"))
        naive = sweden.astimezone().replace(tzinfo=None)  # how datetime.now() would have stored it
        db.MatrikelAudit.update(created_at=naive).where(db.MatrikelAudit.id == row.id).execute()
        self.login()
        self.assertEqual(self.get("from=2025-01-10&to=2025-01-10").get_json()["total"], 1)
        self.assertEqual(self.get("to=2025-01-09").get_json()["total"], 0)
        self.assertEqual(self.get("from=2025-01-11").get_json()["total"], 0)

    def test_one_snapshot_for_the_whole_page(self):
        """Codex #248 r2: an erasure that commits between the account lookup and the page must not show in half."""
        account = da.register_user("tova-konto@example.com", "pass")
        matrikel.link_member_user(self.person.id, account.id, actor=self.matrikel_user, mode="admin")
        matrikel.write_matrikel_audit(
            account, "kontakt_andrad", self.ms, {"person_id": self.person.id, "fields": ["phone"], "source": "profil"}
        )
        matrikel.unlink_member_user(self.person.id, actor=self.matrikel_user)  # the account keeps its name
        errors = []

        def erase_in_another_transaction():
            try:
                matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
            except Exception as exc:  # reported below, not swallowed
                errors.append(exc)
            finally:
                db.DB_PROXY.close()

        real = matrikel._masked_actor_rows

        def masked_rows_then_erase():
            found = real()
            worker = threading.Thread(target=erase_in_another_transaction)
            worker.start()
            worker.join()
            return found

        with patch.object(matrikel, "_masked_actor_rows", masked_rows_then_erase):
            during = matrikel.query_matrikel_audit(full_access=True, membership_id=self.ms.id)
        self.assertEqual(errors, [])
        self.assertTrue(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_anonymized").exists())
        row = next(r for r in during["rows"] if r["action"] == "kontakt_andrad")
        # the state before the erasure, whole: her name and her account, never "Borttagen person" beside the account
        self.assertEqual((row["person"]["name"], row["actor"]["name"]), ("Tova Testsson", "tova-konto@example.com"))
        self.assertNotIn("person_anonymized", [r["action"] for r in during["rows"]])
        after = matrikel.query_matrikel_audit(full_access=True, membership_id=self.ms.id)
        row = next(r for r in after["rows"] if r["action"] == "kontakt_andrad")
        self.assertEqual(row["actor"], {"id": None, "name": matrikel.REDACTED_VALUE})

    def test_manager_filters_only_on_the_shown_actor_name(self):
        """Codex #248 r2: a hit on a handler's e-mail would confirm an address the manager is never shown."""
        handler = da.register_user("handlaggare.post@example.com", "pass", username="handlaggare")
        matrikel.write_matrikel_audit(handler, "person_removed", self.ms, {"person_id": self.person.id})

        def found(query):
            data = self.get(query).get_json()
            return data["total"], len(data["rows"])

        self.login("man")
        self.assertEqual(self.get("").get_json()["rows"][0]["actor"]["name"], "handlaggare")
        for query, expected in (
            ("actor=handlaggare.post@example.com", (0, 0)),
            ("actor=handlaggare.post@example.com&page=3", (0, 0)),  # an empty page tells no total either
            ("actor=HANDLAGGARE", (1, 1)),
            ("actor=handlaggare&page=3", (1, 0)),
        ):
            with self.subTest(query=query):
                self.assertEqual(found(query), expected)
        self.client.get("/api/logout")
        self.login()  # admin sees the account page with both, so may search by either
        self.assertEqual(found("actor=handlaggare.post@example.com"), (1, 1))

    def test_corrected_link_keeps_the_handlers_other_rows_named(self):
        """Codex #248 r3/r4: a handler's account linked to her by mistake, corrected before her erasure, stays in use.
        Only her self-service while linked is masked; the handler's own acts, about her too, keep the name."""
        handler = da.register_user("handlaggare.post@example.com", "pass", username="handlaggare")
        matrikel.link_member_user(self.person.id, handler.id, actor=self.matrikel_user, mode="admin")
        matrikel.write_matrikel_audit(  # while linked to her: her self-service, as the log sees it
            handler, "kontakt_andrad", self.ms, {"person_id": self.person.id, "fields": ["phone"], "source": "profil"}
        )
        matrikel.unlink_member_user(self.person.id, actor=self.matrikel_user)
        matrikel.write_matrikel_audit(  # about her, after the correction: the handler's own act
            handler, "person_updated", self.ms, {"person_id": self.person.id, "before": {}, "after": {}}
        )
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), handler)
        matrikel.write_matrikel_audit(handler, "membership_retired", self.other_ms, {"ended_person_ids": []})
        self.login()
        rows = self.get().get_json()["rows"]
        actors = {(r["action"], r["membership"]["id"]): r["actor"]["name"] for r in rows if r["actor"]}
        named = "handlaggare"
        self.assertEqual(
            {
                key: actors[key]
                for key in (
                    ("kontakt_andrad", self.ms.id),
                    ("person_updated", self.ms.id),
                    ("person_anonymized", self.ms.id),
                    ("membership_retired", self.other_ms.id),
                )
            },
            {
                ("kontakt_andrad", self.ms.id): matrikel.REDACTED_VALUE,
                ("person_updated", self.ms.id): named,
                ("person_anonymized", self.ms.id): named,
                ("membership_retired", self.other_ms.id): named,
            },
        )
        found = self.get("actor=handlaggare").get_json()
        self.assertEqual(
            sorted(r["action"] for r in found["rows"]),
            ["membership_retired", "person_anonymized", "person_updated"],
        )
        self.assertEqual(found["total"], 3)
