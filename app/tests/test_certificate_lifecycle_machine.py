"""
State machine for the certificate of an individual (utils/certificate_lifecycle.py).

Random sequences of the real endpoints: a manager assigns a paper certificate (PATCH /api/individual), the breeder
issues (POST /api/v2/certificates/issue) or re-issues (PATCH .../update) a digital one, a user without rights tries
the same (admin and manager are refused), and the public verify page is read for every token issued so far.
The model is a CertState advanced only by next_state. After every step the database is in the modelled state, a
step succeeds exactly when the table has a row for it, and a verify page says is_current only for the newest token
of a digitally certified rabbit.
PDF generation, signing and S3 are stubbed: the machine is about state.

isort:skip_file
"""

import itertools
import os
import unittest
from collections import Counter
from unittest.mock import mock_open, patch

import utils.cert_service_v2 as cert_service
import utils.database as db
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test
from utils.certificate_lifecycle import TRANSITIONS, CertState, Event, next_state, state_of

from tests.database_test import _USE_POSTGRES
from tests.test_certificates_v2_api import CertV2Mixin
from tests.test_endpoints import FlaskTest

NUMBERS = itertools.count(1)  # unique paper and v1 numbers across sequences
PAPER, ISSUE_NUMBER, ISSUE_PDF = Event.ASSIGN_PAPER, Event.ISSUE_NUMBER, Event.ISSUE_PDF


def walk(state, events):
    """The state after `events` in order, or None when the table lacks a row for one of them."""
    try:
        for event in events:
            state = next_state(state, event)
    except ValueError:
        return None
    return state


def make_machine(case, clients, stats, covered):
    kit = case.individuals[3]  # G1-2112, no certificate in the fixture

    def stored_state():
        ind = db.Individual.get_by_id(kit.id)
        current = db.DigitalCertificateV2.select().where(
            db.DigitalCertificateV2.individual == kit.id, db.DigitalCertificateV2.is_current
        )
        return state_of(ind.certificate, ind.digital_certificate, current.exists())

    class CertificateMachine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            db.DigitalCertificateV2.delete().execute()
            db.Individual.update(certificate=None, digital_certificate=None).where(db.Individual.id == kit.id).execute()
            self.model = CertState.NONE
            self.tokens = []  # verification tokens issued so far, oldest first
            stats["sekvenser"] += 1

        def _step(self, name, actor, events, call, successes, allowed=("manager", "owner")):
            """Calls the endpoint as `actor`; it must succeed exactly when the actor may and the table has a row."""
            after = walk(self.model, events)
            response = call(clients[actor])
            ok = response.status_code in successes and response.get_json().get("status", "success") == "success"
            want = actor in allowed and after is not None
            # A refusal is a typed answer: a crash is a 500, or the legacy PATCH's generic error.
            case.assertLess(response.status_code, 500, f"{name} by {actor} from {self.model}")
            case.assertNotEqual(response.get_json().get("message"), "Kunde inte uppdatera individ.")
            case.assertEqual(ok, want, f"{name} by {actor} from {self.model}: {response.status_code} {response.json}")
            stats[f"{name} {self.model} -> {'ok' if ok else 'nekad'}"] += 1
            if ok:
                for event in events:
                    covered.add((self.model, event))
                    self.model = next_state(self.model, event)
                if "verification_token" in response.json:
                    self.tokens.append(response.json["verification_token"])

        @rule(actor=st.sampled_from(["manager", "viewer"]), blank=st.booleans())
        def assign_paper(self, actor, blank):
            """A paper number, or the blank one the legacy form sends to clear it."""
            body = {
                "id": kit.id,
                "number": kit.number,
                "herd": "G1",
                "certificate": "" if blank else f"PAP-{next(NUMBERS)}",
            }
            name, events = ("CLEAR_PAPER", [Event.CLEAR_PAPER]) if blank else ("ASSIGN_PAPER", [PAPER])
            self._step(name, actor, events, lambda c: c.patch("/api/individual", json=body), successes=(200,))

        @precondition(lambda self: self.model == CertState.DIGITAL_NUMBER)
        @rule(blank=st.booleans())
        def paper_over_v1(self, blank):
            """Its own rule: assign_paper alone reaches these rows too rarely for the coverage assertion."""
            self.assign_paper(actor="manager", blank=blank)

        # The POST endpoint refuses a paper-certified rabbit (convert via update), which the table would allow.
        @precondition(lambda self: self.model != CertState.PAPER)
        @rule(actor=st.sampled_from(["owner", "viewer"]))
        def issue(self, actor):
            url = f"/api/v2/certificates/issue/{kit.number}"
            self._step("ISSUE", actor, [ISSUE_NUMBER, ISSUE_PDF], lambda c: c.post(url, json={}), (201,), ("owner",))

        @rule(actor=st.sampled_from(["owner", "viewer"]))
        def update(self, actor):
            """Re-issue; on a paper-certified rabbit it converts to a digital number first."""
            events = [ISSUE_NUMBER, ISSUE_PDF] if self.model == CertState.PAPER else [ISSUE_PDF]
            url = f"/api/v2/certificates/update/{kit.number}"
            self._step("UPDATE", actor, events, lambda c: c.patch(url, json={}), (200,), ("owner",))

        @precondition(lambda self: self.model != CertState.PAPER)
        @rule(actor=st.sampled_from(["admin", "manager"]), route=st.sampled_from(["issue", "update"]))
        def refused(self, actor, route):
            """Admin and the genebank manager do not attest: refused in every state, nothing changes."""
            if route == "issue":
                self.issue(actor=actor)
            else:
                self.update(actor=actor)

        @precondition(lambda self: self.model == CertState.NONE)
        @rule()
        def legacy_v1(self):
            """Data from before the PDF rows: a digital number and no row."""
            number = 500000 + next(NUMBERS)
            db.Individual.update(digital_certificate=number).where(db.Individual.id == kit.id).execute()
            self.model = CertState.DIGITAL_NUMBER
            stats["legacy v1"] += 1

        @invariant()
        def database_matches_model(self):
            case.assertEqual(stored_state(), self.model)

        @invariant()
        def only_the_newest_token_of_a_digital_rabbit_is_current(self):
            for token in self.tokens:
                response = clients["viewer"].get(f"/api/v2/certificates/verify/{token}")
                case.assertEqual(response.status_code, 200)
                want = self.model == CertState.DIGITAL and token == self.tokens[-1]
                case.assertEqual(response.json["is_current"], want, f"{token} while {self.model}")

    return CertificateMachine


@unittest.skipUnless(_USE_POSTGRES, "needs Postgres")
class TestCertificateStateMachine(CertV2Mixin, FlaskTest):
    def _stub_pdf(self):
        """PDF generation, signing and S3 stubbed: these tests are about state."""
        stubs = (
            patch.object(cert_service._generator, "generate_pedigree", return_value=b"%PDF-1.4 stub"),
            patch.object(cert_service, "sign_pdf", side_effect=lambda pdf, **kw: pdf),
            patch.object(cert_service, "open", mock_open(), create=True),
        )
        for stub in stubs:
            stub.start()
            self.addCleanup(stub.stop)

    def _manager_patch(self, **fields):
        client = self.app.application.test_client(use_cookies=True)
        client.post("/api/login", json={"username": self.manager.email, "password": "pass"})
        kit = self.individuals[3]
        body = {"id": kit.id, "number": kit.number, "herd": "G1", **fields}
        return client.patch("/api/individual", json=body).get_json()

    def test_a_blank_number_clears_a_paper_certificate_and_keeps_the_other_edits(self):
        kit = self.individuals[3]
        db.Individual.update(certificate="PAP-0").where(db.Individual.id == kit.id).execute()
        # Another rabbit already holds "", as one does in production: the column is unique, so the cleared
        # number is stored as NULL or only one rabbit in the registry could ever be cleared.
        db.Individual.update(certificate="").where(db.Individual.id == self.individuals[0].id).execute()
        self.assertEqual(self._manager_patch(certificate="", name="Agnes").get("status", "success"), "success")
        kit = db.Individual.get_by_id(kit.id)
        self.assertEqual((kit.certificate, kit.name), (None, "Agnes"))

    def test_a_row_with_both_numbers_keeps_its_digital_certificate_and_can_be_reissued(self):
        """The old backend could create such a row. No state allows it; a blank number is its way to a legal one."""
        self._stub_pdf()
        kit = self.individuals[3]
        db.Individual.update(certificate="PAP-0", digital_certificate=500000).where(
            db.Individual.id == kit.id
        ).execute()
        admin = self.app.application.test_client(use_cookies=True)  # the breeder: only she may update
        admin.post("/api/login", json={"username": self.owner.email, "password": "pass"})
        url = f"/api/v2/certificates/update/{kit.number}"
        self.assertEqual(admin.patch(url, json={}).status_code, 200)  # as on main: not a crash
        self.assertEqual(self._manager_patch(certificate="").get("status", "success"), "success")
        after = db.Individual.get_by_id(kit.id)
        self.assertEqual((after.certificate, after.digital_certificate), (None, 500000))
        self.assertIs(after.cert_state(), CertState.DIGITAL)  # the PDF row of the re-issue is still current

    def test_a_blank_number_does_not_remove_a_digital_certificate(self):
        kit = self.individuals[3]
        db.Individual.update(digital_certificate=500000).where(db.Individual.id == kit.id).execute()
        # Nothing to clear, so the rest of the edit is saved. On main this request removed the digital number.
        self.assertEqual(self._manager_patch(certificate="", name="Agnes").get("status", "success"), "success")
        after = db.Individual.get_by_id(kit.id)
        self.assertEqual((after.digital_certificate, after.certificate, after.name), (500000, None, "Agnes"))

    def test_random_sequences(self):
        clients = {}
        for name, user in (
            ("owner", self.owner),
            ("admin", self.admin),
            ("manager", self.manager),
            ("viewer", self.viewer),
        ):
            clients[name] = self.app.application.test_client(use_cookies=True)
            clients[name].post("/api/login", json={"username": user.email, "password": "pass"})
        stats, covered = Counter(), set()
        examples = int(os.environ.get("CERT_EXAMPLES", "50"))
        self._stub_pdf()
        run_state_machine_as_test(
            make_machine(self, clients, stats, covered),
            settings=settings(
                max_examples=examples,
                stateful_step_count=20,
                derandomize=True,  # the same sequences every run, so the coverage assertion is not left to chance
                deadline=None,
                database=None,
                suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
            ),
        )
        print("\n".join(f"{k}\t{v}" for k, v in sorted(stats.items())))
        self.assertGreaterEqual(stats["sekvenser"], examples)
        # Every row but the one at creation was driven through an endpoint.
        creation = {(row.source, row.event) for row in TRANSITIONS if row.event == Event.REGISTER_WITH_PAPER}
        self.assertEqual({(r.source, r.event) for r in TRANSITIONS} - creation - covered, set())
