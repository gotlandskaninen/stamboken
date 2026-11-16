#!/usr/bin/env python3
"""
Tests for the yearly report's submission parsing, its effect model (wanted, current, diff) and the dry run (check,
POST …/torrkorning). Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import uuid
from dataclasses import asdict
from datetime import date, datetime

import utils.arsrapport as arsrapport
import utils.database as db
from utils.arsrapport import ArsrapportError, Effect, order, partial_date
from utils.herd_tracking import CONTACT_CONSENT_NEEDED
from utils.individual_commands import ClearFields, RecordDeath, Undo, execute

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import _void, ht_row

LAST = date(2025, 12, 31)
FUTURE = datetime.now().year + 1  # _validate_sale reads the real clock, not the fixture's
BUYER = {"name": "Test Köpare", "town": "Visby"}


def codes(result):
    return {refusal["code"] for refusal in result["refusals"]}


def attest():
    return Effect("attest", LAST, ())


def death(day):
    return Effect("death", day, (day, False, None))


def transfer(day, code="G9002"):
    return Effect("transfer", day, (code,))


class TorrkorningTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(date(2026, 1, 15))
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)

    def parse(self, *entries, paper=False, **fields):
        return arsrapport.parse_submission(self.body(*entries, **fields), paper=paper)

    def paper_body(self, *entries, **fields):
        return self.body(*entries, inbox_item_id=1, received_on="2026-01-10", **fields)

    def dry(self, body, role="owner", paper=False, on=None):
        """check() as `role`, on paper through a taken item, like the route; the route's JSON shape."""
        access = arsrapport.Access(role, self.item() if paper else None)
        sub = arsrapport.parse_submission(body, paper=paper)
        report = arsrapport.current_report(self.h, self.round_)
        refusals, warnings = arsrapport.check(self.h, self.round_, access, report, sub, on=on or arsrapport.today())
        return {
            "ok": not refusals,
            "refusals": [asdict(r) for r in refusals],
            "warnings": [asdict(w) for w in warnings],
        }

    def post(self, body, herd="G9001"):
        return self.api("POST", f"/besattning/{herd}/2025/torrkorning", **body)

    # parse_submission and partial_date

    def test_partial_date_without_day(self):  # a death and a sale alike
        assert partial_date(2025, 2, None, date(2026, 1, 10)) == date(2025, 2, 28)
        assert partial_date(2026, 1, None, date(2026, 1, 10)) == date(2026, 1, 10)
        assert partial_date(2025, 12, 24, date(2026, 1, 10)) == date(2025, 12, 24)

    def test_parse_submission(self):
        a, b, c = self.rabbits(self.h, 3)
        body = self.body(
            self.kvar(a, vikt="2,8", ej_vagd=None),
            self.kvar(b, ej_vagd="Har ingen våg"),
            self.ej_angiven(c),
            defects=[{"individual_id": a.id, "beskrivning": "Snedbett"}],
            reason="  ",
        )
        sub = arsrapport.parse_submission(body, paper=False)
        self.assertEqual(sub.key, uuid.UUID(body["submission_key"]))
        self.assertIsNone(sub.reason)  # blank is no reason
        self.assertEqual(sub.rabbits[a.id].vikt, 2.8)
        self.assertEqual(sub.rabbits[c.id].val, "ej_angiven")
        self.assertEqual(sub.report["not_weighed"], {str(b.id): "Har ingen våg"})
        self.assertEqual(sub.report["not_stated"], [c.id])
        self.assertEqual(sub.report["defects"], [{"individual_id": a.id, "beskrivning": "Snedbett", "foto": None}])
        self.assertIsNone(sub.paper)
        self.assertEqual(
            arsrapport.parse_submission(self.body(self.kvar(a, vikt=2.8)), paper=False).rabbits[a.id].vikt, 2.8
        )

        paper = arsrapport.parse_submission(self.paper_body(), paper=True).paper
        self.assertEqual(paper["received_on"], date(2026, 1, 10))
        self.assertEqual(paper["signed_on"], date(2026, 1, 10))  # P40: the form's date defaults to received_on

        bad = {
            "unknown key": self.body(extra=1),
            "derived key": self.body(not_weighed={}),
            "paper key logged in": self.body(received_on="2026-01-10"),
            "unknown choice": self.body(("1", {"val": "borta"})),
            "vikt nan": self.body(self.kvar(a, vikt="nan")),
            "vikt bool": self.body(self.kvar(a, vikt=True)),
            "dod without date": self.body(self.dod(a, 2025, 13)),
            "dod day zero": self.body(self.dod(a, 2025, 5, 0)),
            "sald day zero": self.body(self.sald(a, "G9002", 2025, 5, 0)),
            "huge year": self.body(self.dod(a, 10**20, 5)),
            "huge vikt": self.body(self.kvar(a, vikt=10**400)),
            "buyer inside the genebank": self.body(self.sald(a, "G9002", 2025, 12, 1, kopare=BUYER)),
            "disease count": self.body(diseases={"rvhd": {"antal": 1001, "alder": "2 år"}}),
            "unknown disease": self.body(diseases={"pest": {"antal": 1, "alder": None}}),
            "defect photo": self.body(defects=[{"individual_id": a.id, "beskrivning": "x", "foto": 7}]),
            "long message": self.body(message="x" * 2001),
        }
        for name, body in bad.items():
            with self.subTest(name), self.assertRaises(ArsrapportError) as caught:
                arsrapport.parse_submission(body, paper=False)
            self.assertEqual(caught.exception.status, 400)
        for name, fields in {
            "no received_on": {"inbox_item_id": 1},
            "signed after received": {"inbox_item_id": 1, "received_on": "2026-01-10", "signed_on": "2026-01-11"},
        }.items():
            with self.subTest(name), self.assertRaises(ArsrapportError):
                arsrapport.parse_submission(self.body(**fields), paper=True)

    # The effect model

    def test_wanted_per_choice(self):
        kvar, dead_dec, dead_jan, sold_dec, sold_jan, unstated, registered = self.rabbits(self.h, 7)
        db.Individual.update(death_date=date(2026, 1, 5)).where(db.Individual.id == registered.id).execute()
        sub = self.parse(
            self.kvar(kvar, vikt=2.8, hull="normal"),
            self.dod(dead_dec, 2025, 11),
            self.dod(dead_jan, 2026, 1, 5),
            self.sald(sold_dec, "G9002", 2025, 12),
            self.sald(sold_jan, "utanfor", 2026, 1, 3),
            self.ej_angiven(unstated),
            self.dod(registered, 2026, 1),
        )
        rows = {row["id"]: row for row in arsrapport.report_list(self.h, 2025)}

        def wanted(ind):
            effects = arsrapport.wanted(sub.rabbits[ind.id], rows[ind.id], None, self.h, 2025, date(2026, 1, 15))
            return sorted(effects, key=lambda e: order(e, LAST))

        self.assertEqual(wanted(kvar), [Effect("weight", LAST, (2.8,)), Effect("bodyfat", LAST, ("normal",)), attest()])
        self.assertEqual(wanted(dead_dec), [death(date(2025, 11, 30))])
        self.assertEqual(wanted(dead_jan), [attest(), death(date(2026, 1, 5))])  # lived on 31/12, no weight needed
        self.assertEqual(wanted(sold_dec), [transfer(LAST)])  # no day: the month's last day
        self.assertEqual(wanted(sold_jan), [attest(), transfer(date(2026, 1, 3), "GX1")])
        self.assertEqual(wanted(unstated), [])
        self.assertEqual(wanted(registered), [attest()])  # the register's exact date is not overwritten

    def test_current_reads_the_reports_rows(self):
        kept, dead, sold = self.rabbits(self.h, 3)
        report = self.reported(
            self.h, self.kvar(kept, vikt=2.8), self.dod(dead, 2025, 11), self.sald(sold, "G9002", 2025, 12, 10)
        )
        attestation = db.HerdTracking.get(db.HerdTracking.individual == kept.id, db.HerdTracking.kind == "ATTESTATION")
        sale = db.HerdTracking.get(db.HerdTracking.individual == sold.id, db.HerdTracking.kind == "TRANSFER")
        weight = db.Weight.get(db.Weight.individual == kept.id)
        death_op = db.IndividualCommand.get(
            db.IndividualCommand.individual == dead.id, db.IndividualCommand.command == "RecordDeath"
        ).operation_id

        self.assertEqual(arsrapport.current(None, kept.id), [])
        current = sorted(arsrapport.current(report, kept.id), key=lambda e: order(e, LAST))
        self.assertEqual(current, [Effect("weight", LAST, (2.8,)), attest()])
        self.assertEqual([e.ref for e in current], [weight.id, attestation.id])
        self.assertEqual(attestation.yearly_herd_report_id, report.id)
        (dead_now,) = arsrapport.current(report, dead.id)
        self.assertEqual((dead_now, dead_now.ref), (death(date(2025, 11, 30)), death_op))
        (sold_now,) = arsrapport.current(report, sold.id)
        self.assertEqual((sold_now, sold_now.ref), (transfer(date(2025, 12, 10)), sale.id))

        _void(attestation, self.admin)
        execute(db.User.get_by_id(self.admin.id), dead.id, lambda ctx: [Undo(death_op, reason="Fel kanin")])
        self.assertEqual(arsrapport.current(report, kept.id), [Effect("weight", LAST, (2.8,))])
        self.assertEqual(arsrapport.current(report, dead.id), [])

    def test_death_an_editor_replaced_or_cleared_is_not_current(self):  # review Important 1
        replaced, cleared, other = self.rabbits(self.h, 3)
        report = self.reported(
            self.h, self.dod(replaced, 2025, 11), self.dod(cleared, 2025, 10), self.kvar(other, vikt=2.8)
        )
        admin = db.User.get_by_id(self.admin.id)
        execute(admin, replaced.id, lambda ctx: [RecordDeath({"death_date": "2025-11-12"})])  # the exact date
        execute(admin, cleared.id, lambda ctx: [ClearFields(frozenset({"death_date", "death_note", "butchered"}))])
        self.assertEqual(arsrapport.current(report, replaced.id), [])
        self.assertEqual(arsrapport.current(report, cleared.id), [])
        # The owner changes another rabbit: nothing tries to undo the deaths.
        body = self.body(self.dod(replaced, 2025, 11), self.dod(cleared, 2025, 10), self.kvar(other, vikt=3.0))
        self.assertTrue(self.dry(body)["ok"])
        # A changed entry for them does not undo the stale death either: the editor's date stands, and a cleared
        # death is written again.
        sub = self.parse(self.dod(replaced, 2025, 11, slaktad=True), self.dod(cleared, 2025, 10, slaktad=True))
        before = self.parse(self.dod(replaced, 2025, 11), self.dod(cleared, 2025, 10)).rabbits
        rows = {row["id"]: row for row in arsrapport.report_list(self.h, 2025, report)}

        def diff(ind):
            entry = sub.rabbits[ind.id]
            want = arsrapport.wanted(entry, rows[ind.id], report, self.h, 2025, date(2026, 1, 15))
            return arsrapport.diff(arsrapport.current(report, ind.id), want, LAST, before[ind.id], entry)

        self.assertEqual(diff(replaced), ([], []))
        october = date(2025, 10, 31)
        self.assertEqual(diff(cleared), ([], [Effect("death", october, (october, True, None))]))
        changed = (self.dod(replaced, 2025, 11, slaktad=True), self.dod(cleared, 2025, 10, slaktad=True))
        self.assertTrue(self.dry(self.body(*changed, self.kvar(other, vikt=2.8)))["ok"])

    def test_diff(self):
        a, b = self.rabbits(self.h, 2)
        jan10, jan20 = date(2026, 1, 10), date(2026, 1, 20)
        diff = arsrapport.diff
        weight = Effect("weight", LAST, (2.8,))
        # unchanged
        self.assertEqual(diff([attest(), weight], [attest(), weight], LAST), ([], []))
        # dead back to kvar
        dead = death(date(2025, 11, 30))
        self.assertEqual(diff([dead], [attest(), weight], LAST), ([dead], [attest(), weight]))
        # the attestation goes: the later sale comes off too, and is written again after it
        sale = transfer(date(2026, 1, 3))
        self.assertEqual(diff([attest(), sale], [sale], LAST), ([attest(), sale], [sale]))
        # the same death or sale input with on moved keeps the current effect
        entry = self.parse(self.dod(a, 2026, 1)).rabbits[a.id]
        self.assertEqual(diff([attest(), death(jan10)], [attest(), death(jan20)], LAST, entry, entry), ([], []))
        self.assertEqual(
            diff([attest(), death(jan10)], [attest(), death(jan20)], LAST), ([death(jan10)], [death(jan20)])
        )
        entry = self.parse(self.sald(b, "utanfor", 2026, 1)).rabbits[b.id]
        cur = [attest(), transfer(jan10, "GX1")]
        self.assertEqual(diff(cur, [attest(), transfer(jan20, "GX1")], LAST, entry, entry), ([], []))
        # kopare on an unchanged sale replaces the transfer, its date kept for a sale without a day
        with_buyer = self.parse(self.sald(b, "utanfor", 2026, 1, kopare=BUYER)).rabbits[b.id]
        remove, add = diff(cur, [attest(), transfer(jan20, "GX1")], LAST, entry, with_buyer)
        self.assertEqual((remove, add), ([transfer(jan10, "GX1")], [transfer(jan10, "GX1")]))

    # check: the rabbits

    def test_unchosen_rabbit_is_not_done(self):
        self.rabbits(self.h, 1)
        self.login("owner")
        r = self.post(self.body()).get_json()
        assert codes(r) == {"inte_klar"} and r["ok"] is False

    def test_adult_needs_weight_or_reason(self):
        (adult,) = self.rabbits(self.h, 1)
        (young,) = self.rabbits(self.h, 1, born=date(2025, 4, 1))
        self.assertEqual(codes(self.dry(self.body(self.kvar(adult), self.kvar(young)))), {"vikt_saknas"})
        self.assertTrue(self.dry(self.body(self.kvar(adult, ej_vagd="Hann inte väga"), self.kvar(young)))["ok"])
        self.assertTrue(self.dry(self.body(self.kvar(adult), self.kvar(young), ending_genbank=True))["ok"])

    def test_weight_comma_grams_and_zero(self):  # Review Focus 6
        (a,) = self.rabbits(self.h, 1)
        result = self.dry(self.body(self.kvar(a, vikt="2,8")))
        self.assertEqual((result["ok"], result["warnings"]), (True, []))
        for vikt in (2800, 0):
            self.assertEqual(codes(self.dry(self.body(self.kvar(a, vikt=vikt)))), {"vikt_ogiltig"})
        result = self.dry(self.body(self.kvar(a, vikt=7.2)))
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["warnings"], [{"individual_id": a.id, "code": "vikt_ovanlig", "message": "Stämmer 7,2 kg?"}]
        )

    def test_ej_angiven_only_on_paper(self):
        (a,) = self.rabbits(self.h, 1)
        self.assertEqual(codes(self.dry(self.body(self.ej_angiven(a)))), {"ej_angiven_digitalt"})
        self.assertEqual(codes(self.dry(self.body(self.ej_angiven(a)), role="manager")), {"ej_angiven_digitalt"})
        self.assertTrue(self.dry(self.paper_body(self.ej_angiven(a)), role="manager", paper=True)["ok"])

    def test_editor_keeps_paper_ej_angiven_and_empty_health(self):  # case 8 by phone
        a, b, c, d = self.rabbits(self.h, 4)
        report = self.reported(
            self.h,
            self.ej_angiven(a),
            self.ej_angiven(b),
            self.ej_angiven(c),
            self.kvar(d, vikt=3.0),
            source="paper",
            health=None,
        )
        kept = self.body(
            self.ej_angiven(a), self.ej_angiven(b), self.kvar(c, vikt=2.8), self.kvar(d, vikt=3.0), health=None
        )
        self.assertTrue(self.dry(kept, role="manager")["ok"])
        new = self.body(self.ej_angiven(a), self.ej_angiven(b), self.kvar(c, vikt=2.8), self.ej_angiven(d), health=None)
        self.assertEqual(
            self.dry(new, role="manager")["refusals"],
            [
                {
                    "individual_id": d.id,
                    "code": "ej_angiven_digitalt",
                    "message": "Ej angiven finns bara när en blankett matas in.",
                }
            ],
        )
        self.assertEqual(codes(self.dry(kept, role="owner")), {"ej_angiven_digitalt", "halsa_saknas"})
        # The manager's logged-in change is the latest submission now: a second call keeps it the same.
        db.YearlyReportSubmission.create(
            report=report,
            submission_key=uuid.uuid4(),
            source="login",
            user=self.manager,
            data=arsrapport.stored_body(kept),
            request_hash="test",
        )
        self.assertTrue(self.dry(kept, role="manager")["ok"])

    def test_caretaker_sale_is_checked_as_a_sale(self):  # step 4a: a proposal, with the sale's own checks
        (a,) = self.rabbits(self.h, 1)
        body = self.body(self.sald(a, "G9002", 2025, 12, 10))
        self.assertTrue(self.dry(body, role="caretaker")["ok"])
        self.assertTrue(self.dry(body, role="owner")["ok"])
        (refusal,) = self.dry(self.body(self.sald(a, "G9999", 2025, 12, 10)), role="caretaker")["refusals"]
        self.assertEqual((refusal["code"], refusal["message"]), ("forsaljning", "Okänd besättning: G9999."))

    def test_sale_messages_come_from_validate_sale(self):
        (a,) = self.rabbits(self.h, 1)
        result = self.dry(self.body(self.sald(a, "G9999", 2025, 12, 10)))
        self.assertEqual(
            result["refusals"], [{"individual_id": a.id, "code": "forsaljning", "message": "Okänd besättning: G9999."}]
        )
        (refusal,) = self.dry(self.body(self.sald(a, "G9002", FUTURE, 1, 1)))["refusals"]
        self.assertEqual(
            (refusal["code"], refusal["message"]), ("forsaljning", "Säljdatumet får inte ligga i framtiden.")
        )

    def test_founder_without_litter_can_be_sold(self):  # P38: no as_dict, which needs a litter
        founder = db.Individual.create(origin_herd=self.h, number="G9001-1801", sex="male", certificate="C-G9001-1801")
        ht_row("BIRTH", herd=self.h, individual=founder, herd_tracking_date=date(2018, 3, 1))
        self.assertTrue(self.dry(self.body(self.sald(founder, "G9002", 2025, 12, 10)))["ok"])

    def test_sale_outside_needs_the_buyer(self):
        (a,) = self.rabbits(self.h, 1)
        self.assertEqual(codes(self.dry(self.body(self.sald(a, "utanfor", 2025, 12, 10)))), {"kopare_saknas"})
        self.assertTrue(self.dry(self.body(self.sald(a, "utanfor", 2025, 12, 10, kopare=BUYER)))["ok"])
        address = {**BUYER, "postal_address": "Testgatan 1"}
        result = self.dry(self.body(self.sald(a, "utanfor", 2025, 12, 10, kopare=address)))
        self.assertEqual(
            result["refusals"], [{"individual_id": a.id, "code": "kopare", "message": CONTACT_CONSENT_NEEDED}]
        )

    def test_changed_sale_is_validated_again(self):  # Codex 2
        (a,) = self.rabbits(self.h, 1, born=date(2025, 10, 1))
        self.reported(self.h, self.sald(a, "G9002", 2025, 12, 10))
        self.assertTrue(self.dry(self.body(self.sald(a, "G9002", 2025, 12, 10)))["ok"])  # the same sale: not checked
        self.assertEqual(codes(self.dry(self.body(self.sald(a, "G9002", FUTURE, 1, 1)))), {"forsaljning"})
        (refusal,) = self.dry(self.body(self.sald(a, "G9002", 2025, 11, 1)))["refusals"]
        self.assertEqual(refusal["code"], "forsaljning")
        self.assertIn("2025-11-13", refusal["message"])  # birth + 43 days: the report's own sale is not in the way
        self.assertTrue(self.dry(self.body(self.sald(a, "G9002", 2025, 12, 5)))["ok"])

    def test_choice_for_a_moved_rabbit_is_refused(self):
        moved, attested, corrected, unchanged = self.rabbits(self.h, 4)
        self.reported(self.h, self.kvar(unchanged, vikt=2.8))
        for ind in (moved, unchanged):
            ht_row("TRANSFER", from_herd=self.h, herd=self.g9002, individual=ind, herd_tracking_date=date(2026, 1, 10))
        ht_row("ATTESTATION", herd=self.h, individual=attested, herd_tracking_date=LAST)
        ht_row("CORRECTION", herd=self.g9002, individual=corrected, herd_tracking_date=date(2026, 1, 3))
        # a choice for via_flytt and redan_rapporterad, and an attestation behind the correction
        result = self.dry(self.body(self.kvar(moved, 2.8), self.kvar(attested, 2.8), self.kvar(corrected, 2.8)))
        self.assertEqual(
            {(r["individual_id"], r["code"]) for r in result["refusals"]},
            {(moved.id, "senare_handelse"), (attested.id, "senare_handelse"), (corrected.id, "senare_handelse")},
        )
        # P39a: no choice for the moved and the attested rabbit, and the report's unchanged choice for a rabbit
        # sold later on the rabbit page, are not refused; the corrected rabbit still needs a choice
        self.assertEqual(
            self.dry(self.body(self.kvar(unchanged, vikt=2.8)))["refusals"],
            [
                {
                    "individual_id": corrected.id,
                    "code": "inte_klar",
                    "message": "Välj Finns kvar, Död eller Såld.",
                }
            ],
        )

    def test_kvar_for_a_rabbit_not_held_on_new_years_eve_is_refused(self):  # spec 5.4 point 1
        (a,) = self.rabbits(self.h, 1)
        self.reported(self.h, self.kvar(a, vikt=2.8))
        # F28: the manager voids the attestation and registers the December sale it hid
        _void(
            db.HerdTracking.get(db.HerdTracking.individual == a.id, db.HerdTracking.kind == "ATTESTATION"), self.admin
        )
        ht_row("TRANSFER", from_herd=self.h, herd=self.g9002, individual=a, herd_tracking_date=date(2025, 12, 20))
        refusal = {
            "individual_id": a.id,
            "code": "inte_innehavare",
            "message": "Kaninen fanns inte i din besättning 31 december.",
        }
        self.assertEqual(self.dry(self.body(self.kvar(a, vikt=3.0)))["refusals"], [refusal])
        self.assertEqual(self.dry(self.body(self.dod(a, 2026, 1, 5)))["refusals"], [refusal])  # lived on 31/12 too
        self.assertTrue(self.dry(self.body(self.kvar(a, vikt=2.8)))["ok"])  # unchanged: writes nothing (P39a)

    def test_death_before_birth_or_after_today_is_refused(self):  # Codex 3; today is 2026-01-15
        (a,) = self.rabbits(self.h, 1, born=date(2025, 4, 1))
        refused = [
            {"individual_id": a.id, "code": "dodsdatum_ogiltigt", "message": arsrapport.REFUSALS["dodsdatum_ogiltigt"]}
        ]
        for ar, manad, dag in ((2025, 1, 1), (2025, 3, None), (2026, 1, 16), (2026, 2, None)):
            with self.subTest(ar=ar, manad=manad, dag=dag):
                self.assertEqual(self.dry(self.body(self.dod(a, ar, manad, dag)))["refusals"], refused)
        for ar, manad, dag in ((2025, 4, None), (2025, 4, 1), (2026, 1, None), (2026, 1, 15)):
            with self.subTest(ar=ar, manad=manad, dag=dag):
                self.assertTrue(self.dry(self.body(self.dod(a, ar, manad, dag)))["ok"])
        self.login("owner")
        response = self.api("POST", "/besattning/G9001/2025/skicka", **self.body(self.dod(a, 2026, 2)))
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, refused))

    def test_unknown_rabbit_and_defect(self):
        (a,) = self.rabbits(self.h, 1)
        stranger = self.individuals[0]  # G1's rabbit
        body = self.body(
            self.kvar(a, vikt=2.8),
            self.kvar(stranger, vikt=2.8),
            defects=[{"individual_id": stranger.id, "beskrivning": "x"}],
        )
        self.assertEqual(  # the rabbit and its defect
            [(r["individual_id"], r["code"]) for r in self.dry(body)["refusals"]], [(stranger.id, "okand_kanin")] * 2
        )

    def test_reason_is_never_checked_against_a_foreign_rabbits_buyer(self):  # Codex re-review 1: no name oracle
        (a,) = self.rabbits(self.h, 1)
        (foreign,) = self.rabbits(self.g9002, 1)
        buyer = db.BuyerContact.create(
            name="Anna Berg", town="Visby", created_by_user=self.admin, purge_at=datetime(2030, 1, 1)
        )
        gx1 = db.Herd.get(db.Herd.herd == "GX1")
        sold = {"individual": foreign, "herd_tracking_date": date(2025, 6, 1), "holder_contact": buyer}
        ht_row("TRANSFER", from_herd=self.g9002, herd=gx1, **sold)
        for reason in ("Anna", "Berg", "Ingen alls"):
            with self.subTest(reason=reason):
                body = self.body(self.kvar(a, vikt=2.8), self.kvar(foreign, vikt=2.8), reason=reason)
                refusals = [(r["individual_id"], r["code"]) for r in self.dry(body)["refusals"]]
                self.assertEqual(refusals, [(foreign.id, "okand_kanin")])

    # check: the report

    def test_message_with_a_phone_number_is_refused(self):
        self.login("owner")
        response = self.post(self.body(message="Ring mig på 070-123 45 67"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["field"], "message")

    def test_free_text_with_contact_details_is_400(self):
        (a,) = self.rabbits(self.h, 1)
        self.login("owner")
        phone = "070-123 45 67"
        bodies = {
            "reason": self.body(reason=f"Ring {phone}"),
            "anteckning": self.body(
                (str(a.id), {"val": "dod", "dod": {"ar": 2025, "manad": 5, "dag": None, "anteckning": phone}})
            ),
            "beskrivning": self.body(defects=[{"individual_id": a.id, "beskrivning": "test@example.invalid"}]),
            "ej_vagd": self.body(self.kvar(a, ej_vagd=f"Annat: ring {phone}")),
            "annat.namn": self.body(diseases={"annat": {"namn": phone, "antal": 1, "alder": None}}),
        }
        for field, body in bodies.items():
            with self.subTest(field):
                response = self.post(body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["field"], field)

    def test_health_required_when_logged_in(self):
        (a,) = self.rabbits(self.h, 1)
        self.assertEqual(codes(self.dry(self.body(self.kvar(a, 2.8), health=None))), {"halsa_saknas"})
        self.assertTrue(self.dry(self.paper_body(self.kvar(a, 2.8), health=None), role="manager", paper=True)["ok"])

    def test_ending_needs_no_choices_and_no_health(self):  # Codex 5, spec 5.7, fråga 18
        self.rabbits(self.h, 1)
        self.assertTrue(self.dry(self.body(health=None, ending_genbank=True))["ok"])
        voluntary = self.body(health="ja", diseases={"rvhd": {"antal": 1, "alder": None}}, ending_genbank=True)
        self.assertTrue(self.dry(voluntary)["ok"])
        self.login("owner")
        response = self.api("POST", "/besattning/G9001/2025/skicka", **self.body(health=None, ending_genbank=True))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNotNone(arsrapport.current_report(self.h, self.round_))

    def test_closed_round_and_reason(self):
        (a,) = self.rabbits(self.h, 1)
        body, late = self.body(self.kvar(a, 2.8)), date(2026, 3, 31)
        self.assertEqual(codes(self.dry(body, on=late)), {"rundan_stangd"})
        self.assertEqual(codes(self.dry(body, on=date(2025, 12, 30))), {"rundan_stangd"})  # before it opens
        self.assertEqual(codes(self.dry(body, role="manager", on=late)), {"orsak_kravs"})
        self.assertTrue(self.dry({**body, "reason": "Blanketten kom sent"}, role="manager", on=late)["ok"])
        paper = self.paper_body(self.kvar(a, 2.8))
        self.assertEqual(codes(self.dry(paper, role="helper", paper=True, on=late)), {"orsak_kravs"})  # P39c
        self.reported(self.h, self.kvar(a, 2.8))
        self.assertEqual(
            codes(self.dry({**paper, "reason": "x"}, role="helper", paper=True, on=late)), {"rundan_stangd"}
        )
        self.assertEqual(codes(self.dry(paper, role="manager", paper=True)), {"orsak_kravs"})  # paper over a report

    def test_dry_run_writes_nothing(self):
        kvar, dead, sold = self.rabbits(self.h, 3)
        self.login("owner")
        models = (db.HerdTracking, db.IndividualCommand, db.MailMessage, db.YearlyHerdReport, db.BuyerContact)
        before = [model.select().count() for model in models]
        body = self.body(
            self.kvar(kvar, vikt=2.8), self.dod(dead, 2025, 11), self.sald(sold, "utanfor", 2025, 12, 10, kopare=BUYER)
        )
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json(), {"ok": True, "refusals": [], "warnings": []})
        self.assertEqual([model.select().count() for model in models], before)
