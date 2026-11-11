"""
State machine for the certificate of an individual (utils/certificate_lifecycle.py).

Random sequences of the real endpoints: a manager assigns a paper certificate (PATCH /api/individual), an admin
issues (POST /api/v2/certificates/issue) or re-issues (PATCH .../update) a digital one, a user without rights tries
the same, and the public verify page is read for every token issued so far. The model is a CertState advanced only
by next_state. After every step the database is in the modelled state, a step succeeds exactly when the table has a
row for it, and a verify page says is_current only for the newest token of a digitally certified rabbit.
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

        def _step(self, name, actor, events, call, successes):
            """Calls the endpoint as `actor`; it must succeed exactly when the actor may and the table has a row."""
            after = walk(self.model, events)
            response = call(clients[actor])
            ok = response.status_code in successes and response.get_json().get("status", "success") == "success"
            want = actor != "viewer" and after is not None
            case.assertEqual(ok, want, f"{name} by {actor} from {self.model}: {response.status_code} {response.json}")
            stats[f"{name} {self.model} -> {'ok' if ok else 'nekad'}"] += 1
            if ok:
                for event in events:
                    covered.add((self.model, event))
                    self.model = next_state(self.model, event)
                if "verification_token" in response.json:
                    self.tokens.append(response.json["verification_token"])

        @rule(actor=st.sampled_from(["manager", "viewer"]))
        def assign_paper(self, actor):
            body = {"id": kit.id, "number": kit.number, "herd": "G1", "certificate": f"PAP-{next(NUMBERS)}"}
            self._step(
                "ASSIGN_PAPER", actor, [PAPER], lambda c: c.patch("/api/individual", json=body), successes=(200,)
            )

        # The POST endpoint refuses a paper-certified rabbit (convert via update), which the table would allow.
        @precondition(lambda self: self.model != CertState.PAPER)
        @rule(actor=st.sampled_from(["admin", "viewer"]))
        def issue(self, actor):
            url = f"/api/v2/certificates/issue/{kit.number}"
            self._step("ISSUE", actor, [ISSUE_NUMBER, ISSUE_PDF], lambda c: c.post(url, json={}), successes=(201,))

        @rule(actor=st.sampled_from(["admin", "viewer"]))
        def update(self, actor):
            """Re-issue; on a paper-certified rabbit it converts to a digital number first."""
            events = [ISSUE_NUMBER, ISSUE_PDF] if self.model == CertState.PAPER else [ISSUE_PDF]
            url = f"/api/v2/certificates/update/{kit.number}"
            self._step("UPDATE", actor, events, lambda c: c.patch(url, json={}), successes=(200,))

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
    def test_random_sequences(self):
        clients = {}
        for name, user in (("admin", self.admin), ("manager", self.manager), ("viewer", self.viewer)):
            clients[name] = self.app.application.test_client(use_cookies=True)
            clients[name].post("/api/login", json={"username": user.email, "password": "pass"})
        stats, covered = Counter(), set()
        examples = int(os.environ.get("CERT_EXAMPLES", "50"))
        stubs = (
            patch.object(cert_service._generator, "generate_pedigree", return_value=b"%PDF-1.4 stub"),
            patch.object(cert_service, "sign_pdf", side_effect=lambda pdf, **kw: pdf),
            patch.object(cert_service, "upload_certificate_v2"),
            patch.object(cert_service, "upload_certificate"),
            patch.object(cert_service, "open", mock_open(), create=True),
        )
        for stub in stubs:
            stub.start()
            self.addCleanup(stub.stop)
        run_state_machine_as_test(
            make_machine(self, clients, stats, covered),
            settings=settings(
                max_examples=examples,
                stateful_step_count=20,
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
