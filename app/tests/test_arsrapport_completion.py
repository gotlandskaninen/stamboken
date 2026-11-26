#!/usr/bin/env python3
"""
Tests for the partial answer (step 6, Task 4): the rabbits a paper form left out, answered on their own through the
personal link or a login, merged with the report under its lock. The draft keeps its other edits (question 1,
alternative A, Jonas 2026-11-26). Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

import json
import threading
import uuid
from datetime import date, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP

from tests.arsrapport_fixtures import ArsrapportTest
from tests.test_purchase_notice import in_thread, run_all

DAY0 = date(2026, 1, 10)
PATH = "/besattning/G9001/2025"


class CompletionTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()  # request_hash reads the app's secret key
        context.push()
        self.addCleanup(context.pop)
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(DAY0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.h2 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        # Case 8: twelve adults, the last the only male; the form leaves out two does and the buck
        self.case, self.left = self.ej_angiven_case(self.h)
        entries = [self.ej_angiven(r) if r in self.left else self.kvar(r, vikt=2.8) for r in self.case]
        self.report = self.reported(self.h, *entries, source="paper", health=None, message="Från blanketten")
        self.doe, self.doe2, self.buck = self.left

    def open_link(self, code=None):
        response = self.client.post(
            "/api/v2/rapport/oppna", json={"token": mail.link_token("rapport", (code or self.code).id)}
        )
        self.assertEqual(response.status_code, 200)

    def answer(self, *entries, key=None, revision=None, path=PATH, dry=False, query=""):
        body = {
            "submission_key": key or str(uuid.uuid4()),
            "revision": self.current().revision if revision is None else revision,
            "rabbits": dict(entries),
        }
        url = f"/api/v2/arsrapport{path}/komplettera{'/torrkorning' if dry else ''}{query}"
        return self.client.post(url, json=body), body

    def current(self):
        return arsrapport.current_report(self.h, self.round_)

    def data(self):
        return json.loads(self.current().data)

    def attested(self, rabbit):
        return (
            db.HerdTracking.select()
            .where(
                db.HerdTracking.individual == rabbit.id,
                db.HerdTracking.kind == "ATTESTATION",
                db.HerdTracking.herd_tracking_date == date(2025, 12, 31),
                db.HerdTracking.voided_at.is_null(),
            )
            .exists()
        )

    def counts(self):
        return [
            m.select().count() for m in (db.YearlyReportSubmission, db.HerdTracking, db.MailMessage, db.SaleProposal)
        ]


class TestCompletion(CompletionTest):
    def test_partial_answer_preserves_report_and_case_8(self):
        before = self.current()
        self.assertFalse(arsrapport.herd_conditions(self.h, self.round_, before)["hane"])
        self.open_link()
        view = self.api("GET", PATH).get_json()["report"]
        self.assertEqual((view["not_stated"], view["can_complete_missing"]), (sorted(r.id for r in self.left), True))
        response, _ = self.answer(self.kvar(self.buck, vikt="3,1"))
        self.assertEqual(response.status_code, 200, response.get_json())
        receipt = response.get_json()
        self.assertEqual(receipt["summary"]["ej_angivna"], 2)
        after = self.current()
        self.assertEqual(after.id, before.id)
        self.assertEqual((after.received_at, after.revision, after.source), (before.received_at, 2, "link"))
        self.assertEqual(self.data()["not_stated"], sorted([self.doe.id, self.doe2.id]))
        self.assertEqual((self.data()["health"], self.data()["message"]), (None, "Från blanketten"))
        self.assertTrue(self.attested(self.buck))
        self.assertFalse(self.attested(self.doe))
        self.assertTrue(all(arsrapport.herd_conditions(self.h, self.round_, after).values()))
        latest = arsrapport._submissions(after)[-1]
        self.assertEqual((latest.access_code_id, latest.user_id, latest.source), (self.code.id, None, "link"))
        self.assertEqual(set(latest.data["rabbits"]), {str(r.id) for r in self.case})  # the whole report again
        view = self.api("GET", PATH).get_json()["report"]  # P9: the latest source is the link, the focus stays
        self.assertEqual(
            (view["not_stated"], view["can_complete_missing"]), (sorted([self.doe.id, self.doe2.id]), True)
        )
        self.answer(self.dod(self.doe, 2025, 6), self.kvar(self.doe2, vikt=2.5))
        self.assertFalse(self.api("GET", PATH).get_json()["report"]["can_complete_missing"])

    def test_completion_keeps_a_pending_sale_and_writes_a_link_sale_as_a_proposal(self):
        self.open_link()
        response, _ = self.answer(self.sald(self.doe, "G9002", 2025, 8, 3))
        self.assertEqual(response.status_code, 200, response.get_json())
        (proposal,) = db.SaleProposal.select()
        self.assertEqual((proposal.individual_id, proposal.state), (self.doe.id, "foreslagen"))
        self.assertEqual(self.answer(self.kvar(self.buck, vikt=3.0))[0].status_code, 200)
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "foreslagen")  # not taken back
        self.assertEqual(self.data()["not_stated"], [self.doe2.id])

    def test_completion_keeps_a_rabbit_left_to_choose_again(self):  # review 1: "välj igen" is val null
        import utils.sale_proposal as sale_proposal  # pylint: disable=import-outside-toplevel

        self.open_link()
        self.assertEqual(self.answer(self.sald(self.doe, "G9002", 2025, 8, 3))[0].status_code, 200)
        (proposal,) = db.SaleProposal.select()
        manager = db.User.get_by_id(self.manager.id)
        sale_proposal.reject(proposal, manager, reason="Fel köpare", then="valj_igen", now=arsrapport.now())
        self.assertEqual(self.answer(self.kvar(self.buck, vikt=3.0))[0].status_code, 200)
        latest = arsrapport._submissions(self.current())[-1]
        self.assertIsNone(latest.data["rabbits"][str(self.doe.id)]["val"])
        (row,) = [r for r in arsrapport.status_view(self.round_, self.gotland.id)["rows"] if r["herd"] == "G9001"]
        self.assertEqual(row["flags"]["forsaljning_avvisad"], 1)
        self.assertTrue(self.api("GET", PATH).get_json()["report"]["from_paper"])

    def test_completion_validates_only_answered_missing_rows(self):
        self.rabbits(self.h, 1)  # registered since: not on the form, and not required now
        self.open_link()
        cases = [
            ((self.kvar(self.buck),), 422),  # an adult needs a weight or Ej vägd
            ((self.dod(self.buck, 2027, 1),), 422),  # a death in a future month
            ((self.kvar(self.case[2], vikt=2.8),), 409),  # not one of the unstated rabbits
            ((self.ej_angiven(self.buck),), 400),
            (((str(self.buck.id), {"val": None}),), 400),
            (
                (
                    (str(self.buck.id), {"val": "kvar", "vikt": 3}),
                    ("0" + str(self.buck.id), {"val": "kvar", "vikt": 3}),
                ),
                400,
            ),
            ((), 400),
        ]
        written = self.counts()
        for entries, status in cases:
            with self.subTest(entries=entries):
                self.assertEqual(self.answer(*entries)[0].status_code, status)
        body = {
            "submission_key": str(uuid.uuid4()),
            "revision": 1,
            "rabbits": dict([self.kvar(self.buck, vikt=3)]),
            "health": "inga",
        }
        self.assertEqual(self.client.post(f"/api/v2/arsrapport{PATH}/komplettera", json=body).status_code, 400)
        self.assertEqual(self.counts(), written)
        response, _ = self.answer(self.kvar(self.buck, vikt=3.0), dry=True)
        self.assertEqual(response.get_json(), {"ok": True, "refusals": [], "warnings": []})
        self.assertEqual(self.counts(), written)  # the dry run writes nothing, mail included
        self.assertEqual(self.answer(self.kvar(self.buck, vikt=3.0))[0].status_code, 200)

    def test_completion_retry_is_bound_to_patch_and_actor(self):
        self.open_link()
        key = str(uuid.uuid4())
        first, _ = self.answer(self.kvar(self.buck, vikt=3.0), key=key)
        self.answer(self.kvar(self.doe, vikt=2.4))  # another change in between
        again, _ = self.answer(self.kvar(self.buck, vikt=3.0), key=key, revision=1)
        self.assertEqual(again.get_json(), first.get_json())
        self.assertEqual(self.answer(self.kvar(self.doe2, vikt=3.0), key=key)[0].status_code, 409)
        ordinary = self.body(*[self.kvar(r, vikt=2.8) for r in self.case], submission_key=key)
        self.assertEqual(self.api("POST", f"{PATH}/skicka", **ordinary).status_code, 409)
        written = self.counts()
        self.assertEqual(self.answer(self.kvar(self.doe2, vikt=3.0), revision=1)[0].status_code, 409)  # stale
        self.assertEqual(self.counts(), written)
        report_code.revoke(self.code, now=arsrapport.now())
        self.assertEqual(self.answer(self.kvar(self.buck, vikt=3.0), key=key, revision=1)[0].status_code, 403)

    def test_completion_role_and_actor_matrix(self):
        self.login("owner")
        self.assertEqual(self.answer(self.kvar(self.buck, vikt=3.0))[0].status_code, 200)
        self.assertEqual(arsrapport._submissions(self.current())[-1].user_id, self.owner.id)
        self.login("hjalp")  # a helper only through a taken paper item, and never here
        self.assertEqual(self.answer(self.kvar(self.doe, vikt=3.0), query="?post=1")[0].status_code, 400)
        self.assertEqual(self.answer(self.kvar(self.doe, vikt=3.0))[0].status_code, 403)
        treasurer = self.user("kassor")
        treasurer.add_role("matrikel_admin", None)
        self.login("kassor")
        self.assertEqual(self.answer(self.kvar(self.doe, vikt=3.0))[0].status_code, 403)
        self.open_link()  # an unrelated login with a valid link: the link's right
        response, _ = self.answer(self.kvar(self.doe, vikt=3.0))
        self.assertEqual(response.status_code, 200, response.get_json())
        latest = arsrapport._submissions(self.current())[-1]
        self.assertEqual((latest.access_code_id, latest.user_id), (self.code.id, None))
        self.login("man")
        self.assertEqual(self.answer(self.kvar(self.doe2, vikt=3.0))[0].status_code, 200)

    def test_the_link_answers_through_the_production_gate(self):  # P8: via=lank, also for an unpromoted account
        self.open_link()
        response, _ = self.answer(self.kvar(self.buck, vikt=3.0), query="?via=lank")
        self.assertEqual(response.status_code, 200, response.get_json())
        account = self.user("ny")  # an account without v2_prod_access, with the link in its session
        self.login("ny")
        self.open_link()
        response, _ = self.answer(self.kvar(self.doe, vikt=3.0), query="?via=lank")
        self.assertEqual(response.status_code, 200, response.get_json())
        latest = arsrapport._submissions(self.current())[-1]
        self.assertEqual((latest.access_code_id, latest.user_id), (self.code.id, None))
        self.assertFalse(db.User.get_by_id(account.id).v2_prod_access)

    def test_nothing_to_complete_after_an_ending_a_withdrawal_or_a_closed_round(self):
        self.open_link()
        data = self.data() | {"ending_genbank": True}
        db.YearlyHerdReport.update(data=json.dumps(data)).where(db.YearlyHerdReport.id == self.report.id).execute()
        self.assertEqual(self.answer(self.kvar(self.buck, vikt=3.0))[0].status_code, 409)
        self.assertFalse(self.api("GET", PATH).get_json()["report"]["can_complete_missing"])
        data["ending_genbank"] = False
        db.YearlyHerdReport.update(data=json.dumps(data)).where(db.YearlyHerdReport.id == self.report.id).execute()
        db.YearlyReportRound.update(end_date=DAY0 - timedelta(days=1)).execute()
        self.login("owner")  # the link has expired with the round; the owner reads it
        self.assertFalse(self.api("GET", PATH).get_json()["report"]["can_complete_missing"])

    def test_a_digital_report_has_no_completion(self):
        rabbits = self.rabbits(self.h2, 2)
        self.owner.add_role("owner", self.h2.id)
        self.reported(self.h2, self.kvar(rabbits[0], vikt=2.8), self.ej_angiven(rabbits[1]))
        self.login("owner")
        response, _ = self.answer(self.kvar(rabbits[1], vikt=3.0), path="/besattning/G9002/2025")
        self.assertEqual(response.status_code, 409)

    def test_two_answers_at_once_one_wins(self):
        self.open_link()
        barrier, results = threading.Barrier(2), {}
        revision = self.current().revision

        def complete(rabbit):
            def run():
                sub = arsrapport.parse_completion(
                    {
                        "submission_key": str(uuid.uuid4()),
                        "revision": revision,
                        "rabbits": dict([self.kvar(rabbit, vikt=3.0)]),
                    }
                )
                barrier.wait(timeout=10)
                access = arsrapport.Access("code", code=self.code)
                return arsrapport.submit(
                    self.h, self.round_, access, report_code.CodeActor(self.code), sub, completion=True
                )

            return run

        self.assertTrue(
            run_all(in_thread(results, "a", complete(self.buck)), in_thread(results, "b", complete(self.doe)))
        )
        outcomes = sorted(isinstance(value, dict) for value in results.values())
        self.assertEqual(outcomes, [False, True], results)
        self.assertIn("Rapporten har ändrats", str([v for v in results.values() if isinstance(v, str)]))
        self.assertEqual(len(self.data()["not_stated"]), 2)
        self.assertEqual(self.current().revision, revision + 1)


class TestRaces(CompletionTest):
    """P11: real PostgreSQL transactions started together; no deadlock, and no partial write."""

    def race(self, **work):
        barrier, results = threading.Barrier(len(work)), {}

        def started(fn):
            def run():
                barrier.wait(timeout=10)
                return fn()

            return run

        self.assertTrue(run_all(*(in_thread(results, name, started(fn)) for name, fn in work.items())))
        return results

    def complete(self, rabbit, revision):
        sub = arsrapport.parse_completion(
            {"submission_key": str(uuid.uuid4()), "revision": revision, "rabbits": dict([self.kvar(rabbit, vikt=3.0)])}
        )
        access = arsrapport.Access("code", code=self.code)
        return arsrapport.submit(self.h, self.round_, access, report_code.CodeActor(self.code), sub, completion=True)

    def test_completion_races_approval_of_another_sale(self):
        import utils.sale_proposal as sale_proposal  # pylint: disable=import-outside-toplevel

        self.open_link()
        self.assertEqual(self.answer(self.sald(self.doe, "G9002", 2025, 8, 3))[0].status_code, 200)
        (proposal,) = db.SaleProposal.select()
        manager, revision = db.User.get_by_id(self.manager.id), self.current().revision
        results = self.race(
            answer=lambda: self.complete(self.buck, revision),
            approve=lambda: sale_proposal.approve(proposal, manager, now=arsrapport.now()).id,
        )
        self.assertIsInstance(results["answer"], dict, results)
        self.assertIsInstance(results["approve"], int, results)
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "godkand")
        self.assertTrue(self.attested(self.buck))
        self.assertEqual(self.data()["not_stated"], [self.doe2.id])

    def test_completion_races_withdrawal(self):
        self.open_link()
        revision, access = self.current().revision, arsrapport.Access("code", code=self.code)
        actor = report_code.CodeActor(self.code)
        results = self.race(
            answer=lambda: self.complete(self.buck, revision),
            withdraw=lambda: arsrapport.withdraw(self.h, self.round_, access, actor, revision=revision) and "ok",
        )
        won = [name for name, value in results.items() if not (isinstance(value, str) and "Error" in value)]
        self.assertEqual(len(won), 1, results)  # the other is refused, never half done
        submitted = db.YearlyHerdReport.select().where(db.YearlyHerdReport.status == "submitted")
        if won == ["withdraw"]:
            self.assertFalse(submitted.exists())
            self.assertFalse(self.attested(self.buck))
        else:
            self.assertEqual(submitted.count(), 1)
            self.assertTrue(self.attested(self.buck))


class TestDraft(CompletionTest):
    def draft(self, **rabbits):
        """A member's draft from Ändra: the submitted rabbits, with `rabbits` (id: entry) changed, in body and form."""
        submitted = arsrapport._submissions(self.current())[-1].data["rabbits"]
        body = {**submitted, **rabbits}
        form = {
            key: {**entry, "vikt": "" if entry.get("vikt") is None else str(entry["vikt"])}
            for key, entry in body.items()
        }
        return db.YearlyReportDraft.create(
            herd=self.h,
            round=self.round_,
            data={"rabbits": body, "health": None, "message": "Utkast", "form": {"rabbits": form, "message": "Utkast"}},
            submission_key=uuid.uuid4(),
            updated_at=arsrapport.now(),
            updated_by_access_code=self.code.id,
        )

    def test_completion_preserves_unrelated_draft_edits(self):
        other = self.case[2]
        edited = dict([self.dod(other, 2025, 9)])
        draft = self.draft(**edited, **dict([self.kvar(self.doe, vikt=9.9)]))  # the doe changed in the draft too
        self.open_link()
        response, body = self.answer(self.kvar(self.buck, vikt=3.1), self.kvar(self.doe, vikt=2.4))
        self.assertEqual(response.status_code, 200, response.get_json())
        kept = db.YearlyReportDraft.get_by_id(draft.id)
        for part in (kept.data, kept.data["form"]):
            self.assertEqual(part["rabbits"][str(other.id)]["val"], "dod")  # the unrelated edit stays
            self.assertEqual(part["rabbits"][str(self.buck.id)]["val"], "kvar")  # "Ej angiven" takes the answer
        self.assertEqual(kept.data["rabbits"][str(self.doe.id)]["vikt"], 9.9)  # the member's own edit stays
        self.assertEqual(kept.data["form"]["rabbits"][str(self.buck.id)]["vikt"], "3,1")
        self.assertEqual(kept.data["rabbits"][str(self.buck.id)]["vikt"], 3.1)
        self.assertEqual((kept.data["message"], kept.submission_key), ("Utkast", draft.submission_key))
        self.assertGreater(kept.updated_at, draft.updated_at)  # the clock stands still: the version moves anyway
        stale = self.api(
            "PUT",
            f"{PATH}/utkast",
            data={"rabbits": {}},
            updated_at=draft.updated_at.isoformat(),
            submission_key=str(draft.submission_key),
            revision=2,
        )
        self.assertEqual(stale.status_code, 409)  # an autosave from before the answer
        self.assertNotEqual(str(kept.submission_key), body["submission_key"])

    def test_a_draft_bound_to_the_completion_key_lets_it_go(self):
        draft = self.draft()
        self.open_link()
        response, _ = self.answer(self.kvar(self.buck, vikt=3.1), key=str(draft.submission_key))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.YearlyReportDraft.get_by_id(draft.id).submission_key)

    def test_an_ordinary_submission_still_deletes_the_draft(self):
        self.draft()
        self.open_link()
        self.answer(self.kvar(self.buck, vikt=3.1), self.kvar(self.doe, vikt=2.4), self.kvar(self.doe2, vikt=2.4))
        body = self.body(*[self.kvar(r, vikt=2.8) for r in self.case], revision=self.current().revision)
        response = self.api("POST", f"{PATH}/skicka", **body)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(db.YearlyReportDraft.select().exists())
