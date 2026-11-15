"""Shared setup for the yearly report's tests: a round, certified rabbits, a main member, the clock and bodies.

Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

import json
import uuid
from datetime import date, datetime, time, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
from utils.individual_commands import RecordAttestation, RecordDeath, SetMeasurements, TransferIndividual, execute

from tests.ht_helpers import ht_row
from tests.inbox_fixtures import InboxTest

GENEBANKS = ("Gotlandskanin", "Mellerudskanin")  # the real names of DatabaseTest's "Gotland" and "Mellerud"


def _entry(ind, val, **fields):
    return str(ind.id), {"val": val, "vikt": None, "ej_vagd": None, "hull": None, "dod": None, "sald": None, **fields}


class ArsrapportTest(InboxTest):
    def setUp(self):
        super().setUp()
        self.gotland, self.mellerud = self.genebanks
        self._number = 0

    def round(self, year=2025, activate=("Gotlandskanin",)):
        """The year's round with the default dates, activated by the admin for the genebanks named."""
        round_ = db.YearlyReportRound.create(report_year=year, created_by=self.admin, **arsrapport.default_dates(year))
        for name in activate:
            arsrapport.activate(round_, self.genebanks[GENEBANKS.index(name)].id, self.admin)
        return round_

    def rabbits(self, herd, n, born=date(2024, 5, 1), sexes=("female", "male")):
        """`n` certified rabbits of one litter born in `herd`, `sexes` in turn; birth rows make `herd` their holder."""
        litter = db.Breeding.create(
            breeding_herd_id=herd, breed_date=born - timedelta(days=31), birth_date=born, litter_size=n, litter_size6w=n
        )
        rabbits = []
        for k in range(n):
            self._number += 1
            number = f"{herd.herd}-{born:%y}{self._number:03d}"
            rabbit = db.Individual.create(
                origin_herd=herd, breeding=litter, number=number, sex=sexes[k % len(sexes)], certificate=f"C-{number}"
            )
            ht_row("BIRTH", herd=herd, individual=rabbit, herd_tracking_date=born)
            rabbits.append(rabbit)
        return rabbits

    def main_member(self, herd, email="g1@example.invalid"):
        """A membership owning `herd`, and its main member; set the member's `user` to make that account the owner."""
        membership = db.Membership.create()
        db.Herd.update(membership=membership).where(db.Herd.id == herd.id).execute()
        herd.membership = membership
        return db.Member.create(
            first_name="Test", last_name="Huvudmedlem", email=email, membership=membership, role="huvudmedlem"
        )

    def at(self, when):
        """Sets utils.arsrapport.now to `when`; a date means noon that day in Stockholm."""
        if not isinstance(when, datetime):
            when = datetime.combine(when, time(12), arsrapport.STOCKHOLM)
        patcher = mock.patch.object(arsrapport, "now", return_value=when)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def kvar(ind, vikt=None, hull=None, ej_vagd=None):
        return _entry(ind, "kvar", vikt=vikt, hull=hull, ej_vagd=ej_vagd)

    @staticmethod
    def ej_angiven(ind):
        return _entry(ind, "ej_angiven")

    @staticmethod
    def dod(ind, ar, manad, dag=None, slaktad=False):
        return _entry(ind, "dod", dod={"ar": ar, "manad": manad, "dag": dag, "slaktad": slaktad, "anteckning": None})

    @staticmethod
    def sald(ind, till, ar, manad, dag=None, kopare=None):
        return _entry(ind, "sald", sald={"till": till, "ar": ar, "manad": manad, "dag": dag, "kopare": kopare})

    @staticmethod
    def body(*entries, **report_fields):
        """A logged-in submission body with the rabbits of `entries` (kvar, dod, sald); `report_fields` override."""
        return {
            "submission_key": str(uuid.uuid4()),
            "revision": None,
            "reason": None,
            "rabbits": dict(entries),
            "ending_genbank": False,
            "membership_after_end": None,
            "health": "inga",
            "diseases": {},
            "defects": [],
            "message": "",
            **report_fields,
        }

    def api(self, method, path, **json):
        """`method` on /api/v2/arsrapport`path`, with `json` as the body."""
        return self.client.open(f"/api/v2/arsrapport{path}", method=method, json=json)

    def reported(self, herd, *entries, source="login", year=2025, **report_fields):
        """
        A submitted report for `herd` whose one submission wrote the entries' effects through execute, as the admin,
        with Task 7's operation_ids and added_measurements; built by hand until submit exists.
        """
        admin = db.User.get_by_id(self.admin.id)
        body = self.body(*entries, **report_fields)
        sub = arsrapport.parse_submission(body, paper=False)
        rows = {row["id"]: row for row in arsrapport.report_list(herd, year)}
        report = db.YearlyHerdReport.create(
            herd=herd,
            round=arsrapport.get_round(year),
            report_date=arsrapport.today(),
            data=json.dumps(sub.report),
            status="submitted",
            source=source,
            revision=1,
            received_at=arsrapport.now(),
        )
        last, start = date(year, 12, 31), db.IndividualCommand.select(db.fn.MAX(db.IndividualCommand.id)).scalar()
        added = []
        for rabbit, entry in sub.rabbits.items():
            effects = arsrapport.wanted(entry, rows[rabbit], None, herd, year, arsrapport.today())
            for effect in sorted(effects, key=lambda e: arsrapport.order(e, last)):
                command = self._command(effect, rabbit, herd, report, entry)
                execute(admin, rabbit, lambda ctx, command=command: [command])
                if effect.kind in ("weight", "bodyfat"):
                    model = db.Weight if effect.kind == "weight" else db.Bodyfat
                    # the newest row: weight is a real column, so 2.8 does not match it exactly (D17)
                    row = model.filter(individual=rabbit).order_by(model.id.desc()).first()
                    added.append(
                        {
                            "individual_id": rabbit,
                            "kind": effect.kind,
                            "id": row.id,
                            "date": effect.date.isoformat(),
                            "value": effect.value[0],
                        }
                    )
        commands = db.IndividualCommand.select(db.IndividualCommand.operation_id).where(
            db.IndividualCommand.id > (start or 0)
        )
        db.YearlyReportSubmission.create(
            report=report,
            submission_key=sub.key or uuid.uuid4(),
            created_at=arsrapport.now(),
            source=source,
            user=admin,
            operation_ids=[str(op) for (op,) in commands.tuples()],
            added_measurements=added,
            data=arsrapport.stored_body(body),
            request_hash="test",
        )
        return report

    @staticmethod
    def _command(effect, rabbit, herd, report, entry):
        when = effect.date.isoformat()
        if effect.kind == "attest":
            return RecordAttestation(herd.herd, when, report=report.id)
        if effect.kind == "death":
            return RecordDeath({"death_date": when, "butchered": effect.value[1], "death_note": effect.value[2]})
        if effect.kind == "transfer":
            return TransferIndividual(effect.value[0], when, buyer=entry.sald["kopare"])
        if effect.kind == "weight":
            stored = [
                {"weight": w.weight, "date": w.weight_date.isoformat()} for w in db.Weight.filter(individual=rabbit)
            ]
            return SetMeasurements(weights=[*stored, {"weight": effect.value[0], "date": when}])
        stored = [
            {"bodyfat": b.bodyfat, "date": b.bodyfat_date.isoformat()} for b in db.Bodyfat.filter(individual=rabbit)
        ]
        return SetMeasurements(bodyfat=[*stored, {"bodyfat": effect.value[0], "date": when}])
