"""
State machine for the membership status (utils.membership_lifecycle), driven through the real endpoints.

Random sequences of create, PATCH status (both endpoints), retire, GDPR erasure of the main member, add and
swap of the main member, against a model that is advanced only by `next_state`. After every step the model
equals `state_of(status, has_main)` read from the database, and a status change the table has no row for
must answer 409 (every other step must succeed).

isort:skip_file
"""

import os
import unittest
from collections import Counter

import utils.data_access as da
import utils.database as db
from herdbook import APP, limiter
from hypothesis import HealthCheck, assume, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test
from utils.membership_lifecycle import Event, State, Status, TransitionRefused, next_state, state_of

from tests.database_test import _USE_POSTGRES, DatabaseTest

limiter.enabled = False
WITH_MAIN = (State.ACTIVE, State.PENDING, State.FRIEXEMPLAR, State.PAUSED)
STATUSES = st.sampled_from([s.value for s in Status])


def make_machine(case, stats):
    client = case.client

    def call(method, url, body=None):
        resp = getattr(client, method)(url, json=body)
        return resp.status_code, resp.get_json(silent=True)

    class MembershipMachine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.model = {}  # membership id -> State
            stats["sekvenser"] += 1

        def teardown(self):  # the requests commit (and teardown_request rolls back), so delete instead
            for table in (db.MatrikelAudit, db.HerdAccessGrant, db.Member, db.Membership):
                table.delete().execute()

        # -- what the database says (preconditions only; the model is never read from it) ---------------------
        @staticmethod
        def _status(mid):
            return db.Membership.get_by_id(mid).membership_status

        @staticmethod
        def _active(mid, main):
            role_is_main = db.Member.role == "huvudmedlem"
            return (
                db.Member.select()
                .where(
                    db.Member.membership == mid,
                    db.Member.end_date.is_null(True),
                    role_is_main if main else ~role_is_main,
                )
                .first()
            )

        def _apply(self, mid, event, target=None):
            self.model[mid] = next_state(self.model[mid], event, target)
            stats[f"{event}: ok"] += 1

        @precondition(lambda self: len(self.model) < 3)
        @rule(status=STATUSES)
        def create(self, status):
            code, body = call(
                "post", "/api/v2/memberships", {"first_name": "A", "last_name": "B", "membership_status": status}
            )
            assert code == 201, (code, body)
            self.model[body["id"]] = next_state(None, Event.CREATE, status)
            stats["CREATE: ok"] += 1

        @precondition(lambda self: self.model)
        @rule(data=st.data(), status=STATUSES, endpoint=st.sampled_from(["memberships", "members"]))
        def set_status(self, data, status, endpoint):
            mid = data.draw(st.sampled_from(sorted(self.model)))
            code, body = call("patch", f"/api/v2/{endpoint}/{mid}", {"membership_status": status})
            try:
                after = next_state(self.model[mid], Event.SET_STATUS, status)
            except TransitionRefused:
                assert code == 409, (
                    f"{self.model[mid]} -> {status} via {endpoint} answered {code}, the table has no row"
                )
                stats[f"SET_STATUS: refused ({endpoint})"] += 1
                return
            assert code == 200, (code, body)
            self.model[mid] = after
            stats[f"SET_STATUS: ok ({endpoint})"] += 1

        @precondition(lambda self: self.model)
        @rule(data=st.data())
        def retire(self, data):
            mid = data.draw(st.sampled_from(sorted(self.model)))
            code, body = call("delete", f"/api/v2/memberships/{mid}")
            assert code == 200, (code, body)
            self._apply(mid, Event.RETIRE)

        @precondition(lambda self: self.model)
        @rule(data=st.data())
        def erase_main(self, data):
            mid = data.draw(st.sampled_from(sorted(self.model)))
            main = self._active(mid, main=True)
            assume(main is not None)
            code, body = call("post", f"/api/v2/persons/{main.id}/anonymize")
            assert code == 200, (code, body)
            self._apply(mid, Event.ERASE_MAIN)

        @precondition(lambda self: self.model)
        @rule(data=st.data(), role=st.sampled_from(["huvudmedlem", "familjemedlem"]))
        def add_person(self, data, role):
            mid = data.draw(st.sampled_from(sorted(self.model)))
            status = self._status(mid)
            assume(status != Status.INACTIVE and (role != "huvudmedlem" or self.model[mid] is State.HEADLESS))
            code, body = call(
                "post", f"/api/v2/memberships/{mid}/persons", {"first_name": "C", "last_name": "D", "role": role}
            )
            assert code == 201, (code, body)
            if role == "huvudmedlem":
                self._apply(mid, Event.ADD_MAIN, status)

        @precondition(lambda self: self.model)
        @rule(data=st.data())
        def swap_main(self, data):
            mid = data.draw(st.sampled_from(sorted(self.model)))
            other = self._active(mid, main=False)
            assume(other is not None)
            code, body = call("post", f"/api/v2/memberships/{mid}/main-member", {"person_id": other.id})
            assert code == 200, (code, body)
            if self.model[mid] in (State.HEADLESS, State.RETIRED):
                self._apply(mid, Event.ADD_MAIN, self._status(mid))

        @invariant()
        def database_matches_model(self):
            for mid, state in self.model.items():
                real = state_of(self._status(mid), self._active(mid, main=True) is not None)
                assert real is state, f"membership {mid}: database says {real}, the table says {state}"

    return MembershipMachine


@unittest.skipUnless(_USE_POSTGRES, "needs Postgres: the endpoints commit")
class TestMembershipLifecycleMachine(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        user = da.register_user("matadmin@example.com", "pass", username="matadmin")
        user.add_role("matrikel_admin", None)
        self.client.post("/api/login", json={"username": "matadmin", "password": "pass"})

    def test_random_sequences(self):
        stats = Counter()
        examples = int(os.environ.get("LIFECYCLE_EXAMPLES", "40"))
        run_state_machine_as_test(
            make_machine(self, stats),
            settings=settings(
                max_examples=examples,
                stateful_step_count=15,
                deadline=None,
                database=None,
                suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
            ),
        )
        print("\n".join(f"{k}\t{v}" for k, v in sorted(stats.items())))
        self.assertGreaterEqual(stats["sekvenser"], examples)
