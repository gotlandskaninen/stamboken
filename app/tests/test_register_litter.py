"""
A litter without a certificate (step 4b, Task 1): RegisterLitter and ConfirmLitterSize, and the certificate that
numbers such a litter later. Synthetic herds and rabbits only.

isort:skip_file
"""

import threading
from datetime import date, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.report_code as report_code
import utils.settings as settings
from utils.arsrapport import ReportGrant
from utils.herd_tracking import record_herd_tracking
from utils.individual_commands import IndividualRefused, SameLitter, confirm_litter_size, register_litter
from utils.individual_number_v2 import number_from_certificate
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row, make_individual

BORN = date(2025, 5, 10)
URL = "/api/v2/individual"


class LitterTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.g1, self.g2, self.m3 = self.herds
        self.doe = self.adult(self.g1, "G1-2411", "female")
        self.buck = self.adult(self.g2, "G2-2412", "male")  # the same genebank, another herd
        self.other_owner = self.user("owner2", ("owner", self.g2.id))

    @staticmethod
    def adult(herd, number, sex):
        rabbit = make_individual(herd, number, date(2024, 5, 1), sex=sex)
        ht_row("BIRTH", herd=herd, individual=rabbit, herd_tracking_date=date(2024, 5, 1))
        return rabbit

    def add(self, user=None, *, born=BORN, size=5, size6w=None, mother=None, father=None, herd="G1", **options):
        return register_litter(
            user or self.owner,
            (mother or self.doe).id,
            (father or self.buck).id,
            born,
            size,
            size6w,
            herd,
            year=options.pop("year", born.year),
            **options,
        )

    def litters(self):
        return db.Breeding.select().where(db.Breeding.mother == self.doe.id).count()


class TestRegisterLitter(LitterTest):
    def test_register_litter_one_step(self):
        litter = self.add()
        self.assertEqual(
            (litter.breeding_herd_id.herd, litter.mother_id, litter.father_id, litter.birth_date, litter.breed_date),
            ("G1", self.doe.id, self.buck.id, BORN, BORN - timedelta(days=31)),
        )
        self.assertIsNone(litter.litter_number)
        self.assertEqual((litter.litter_size, litter.litter_size6w, litter.litter_size6w_preliminary), (5, 5, True))
        command = db.IndividualCommand.get(db.IndividualCommand.individual == self.doe.id)
        self.assertEqual((command.command, command.actor_id), ("RegisterLitter", self.owner.id))
        self.assertEqual(command.after["breeding"], litter.id)

    def test_a_given_count_is_not_preliminary_and_may_be_zero(self):
        litter = self.add(size6w=0)
        self.assertEqual((litter.litter_size6w, litter.litter_size6w_preliminary), (0, False))

    def test_same_mother_within_three_days_is_409(self):
        first = self.add()
        for born, father in ((BORN + timedelta(days=2), None), (BORN, None), (BORN - timedelta(days=3), self.buck)):
            with self.subTest(born=str(born)), self.assertRaises(SameLitter) as raised:
                self.add(born=born, father=father)
            self.assertEqual(raised.exception.status, 409)
            self.assertEqual(
                {key: raised.exception.envelope[key] for key in ("code", "breeding_id")},
                {"code": "samma_kull", "breeding_id": first.id},
            )
        self.assertEqual(self.litters(), 1)

    def test_ny_kull_skips_only_the_three_day_check(self):
        first = self.add()
        # The 35-day rule of every other route still holds, so a litter 2 days later is refused for that...
        with self.assertRaises(IndividualRefused) as raised:
            self.add(born=BORN + timedelta(days=2), ny_kull=True)
        self.assertNotIsInstance(raised.exception, SameLitter)
        self.assertIn("inom 35 dagar", raised.exception.envelope["message"])
        # ...and the unique (mother, father, birth date) is not skipped either.
        with self.assertRaises(SameLitter) as same:
            self.add(ny_kull=True)
        self.assertEqual(
            (same.exception.envelope["code"], same.exception.envelope["breeding_id"]), ("kullen_finns", first.id)
        )
        later = self.add(born=BORN + timedelta(days=40), ny_kull=True)
        self.assertNotEqual(later.id, first.id)

    def test_mother_outside_herd_refused(self):
        stranger = self.adult(self.g2, "G2-2413", "female")
        with self.assertRaises(IndividualRefused) as raised:
            self.add(mother=stranger)  # the owner of G1 names her own herd and another herd's doe
        self.assertEqual(raised.exception.envelope["message"], "Modern fanns inte i besättningen vid födelsedatumet.")
        with self.assertRaises(IndividualRefused) as forbidden:
            self.add(mother=stranger, herd="G2")  # the doe's herd is not the owner's
        self.assertEqual(forbidden.exception.envelope["message"], "Forbidden")
        self.assertFalse(db.Breeding.select().where(db.Breeding.mother == stranger.id).exists())

    def test_father_other_genebank_refused(self):
        foreign = self.adult(self.m3, "M3-2412", "male")
        with self.assertRaises(IndividualRefused) as raised:
            self.add(father=foreign)
        self.assertEqual(
            raised.exception.envelope["message"], "Fadern måste vara registrerad i samma genbank som modern."
        )
        self.assertEqual(self.litters(), 0)

    def test_a_viewer_and_the_wrong_herds_owner_are_refused(self):
        for user, herd in ((self.viewer, "G1"), (self.other_owner, "G1")):
            with self.subTest(user=user.username), self.assertRaises(IndividualRefused) as raised:
                self.add(user, herd=herd)
            self.assertEqual(raised.exception.envelope["message"], "Forbidden")
        self.assertEqual(self.litters(), 0)

    def test_manager_and_admin_may_register(self):
        self.assertEqual(self.add(self.manager).breeding_herd_id.herd, "G1")
        self.assertEqual(self.add(self.admin, born=BORN + timedelta(days=60)).breeding_herd_id.herd, "G1")

    def test_litter_date_outside_year_refused(self):
        cases = (
            (date(2024, 6, 1), 2025, "Kullen måste vara född under 2025."),
            (date.today() + timedelta(days=1), date.today().year, "Födelsedatum kan inte vara i framtiden."),
        )
        for born, year, message in cases:
            with self.subTest(born=str(born)), self.assertRaises(IndividualRefused) as raised:
                self.add(born=born, year=year)
            self.assertEqual(raised.exception.envelope["message"], message)
        self.assertEqual(self.litters(), 0)

    def test_litter_sizes_are_validated(self):
        cases = (
            ({"size": 0}, "Ange antal födda (minst 1)."),
            ({"size": 5, "size6w": 6}, "Antal levande vid 6 veckor kan inte vara fler än antal födda."),
            ({"size": 5, "size6w": -1}, "Ange antal levande vid 6 veckor (0 eller fler)."),
        )
        for fields, message in cases:
            with self.subTest(fields=fields), self.assertRaises(IndividualRefused) as raised:
                self.add(**fields)
            self.assertEqual(raised.exception.envelope["message"], message)
        self.assertEqual(self.litters(), 0)

    def test_litter_of_mother_sold_before_new_year(self):
        """L2: the litter is the herd the doe was in at the birth, not the report list or where she is now."""
        record_herd_tracking(self.doe, self.g2, date(2025, 12, 20), "TRANSFER", self.owner)
        litter = self.add()  # the seller registers a litter born in October
        self.assertEqual(litter.breeding_herd_id.herd, "G1")
        for user in (self.other_owner, self.owner):  # the buyer's herd is not the litter's, and no longer the seller's
            with self.subTest(user=user.username), self.assertRaises(IndividualRefused):
                self.add(user, born=date(2025, 10, 1), herd="G2")
        self.assertEqual(confirm_litter_size(self.owner, litter.id, 4).litter_size6w, 4)
        with self.assertRaises(IndividualRefused) as raised:
            confirm_litter_size(self.other_owner, litter.id, 3)
        self.assertEqual(raised.exception.envelope["message"], "Forbidden")

    def test_concurrent_same_litter(self):
        """Two real transactions for one mother and date: one litter, and the other gets samma_kull (L3)."""
        barrier = threading.Barrier(2, timeout=10)
        outcomes = []

        def tab():
            try:
                db.DATABASE.connect(reuse_if_open=True)
                barrier.wait()
                outcomes.append(self.add())
            except Exception as exc:  # noqa: BLE001 — a deadlock or an IntegrityError lands here and fails below
                outcomes.append(exc)
            finally:
                db.DATABASE.close()

        threads = [threading.Thread(target=tab) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads), "hung or deadlocked")
        litters = [o for o in outcomes if isinstance(o, db.Breeding)]
        refused = [o for o in outcomes if isinstance(o, SameLitter)]
        self.assertEqual((len(litters), len(refused)), (1, 1), outcomes)
        self.assertEqual(refused[0].envelope["breeding_id"], litters[0].id)
        self.assertEqual(self.litters(), 1)


class TestLitterByLink(LitterTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(date(2026, 1, 15))
        self.round_ = self.round(2025)
        self.main_member(self.g1, "g1@example.invalid")
        self.code = report_code.issue_code(
            self.g1, self.round_, db.Member.get(db.Member.membership == self.g1.membership), now=arsrapport.now()
        )
        self.actor = CodeActor(self.code)

    def as_code(self, **options):
        return self.add(self.actor, grant=ReportGrant(code=self.code), **options)

    def test_code_actor_may_register_litter(self):
        litter = self.as_code()
        self.assertEqual(self.as_code(born=BORN + timedelta(days=60)).breeding_herd_id.herd, "G1")
        command = db.IndividualCommand.select().where(db.IndividualCommand.individual == self.doe.id).first()
        self.assertEqual(command.after["breeding"], litter.id)
        self.assertEqual((command.actor_id, command.access_code_id), (None, self.code.id))

    def test_code_may_confirm_its_herds_litter(self):
        litter = self.as_code()
        confirmed = confirm_litter_size(self.actor, litter.id, 3, grant=ReportGrant(code=self.code))
        self.assertEqual((confirmed.litter_size6w, confirmed.litter_size6w_preliminary), (3, False))

    def test_code_is_refused_another_herd_or_year(self):
        stranger = self.adult(self.g2, "G2-2413", "female")
        with self.assertRaises(IndividualRefused):
            self.add(self.actor, mother=stranger, herd="G2", grant=ReportGrant(code=self.code))
        with self.assertRaises(IndividualRefused):  # the link is for the round's year
            self.add(self.actor, born=date(2024, 8, 1), grant=ReportGrant(code=self.code))
        self.assertEqual(self.litters(), 0)
        with self.assertRaises(IndividualRefused):  # and no grant gives it nothing
            self.add(self.actor)


class TestConfirmLitterSize(LitterTest):
    def test_confirm_clears_preliminary(self):
        litter = self.add()
        self.assertTrue(litter.litter_size6w_preliminary)
        confirmed = confirm_litter_size(self.owner, litter.id, 3)
        self.assertEqual((confirmed.litter_size6w, confirmed.litter_size6w_preliminary), (3, False))
        command = db.IndividualCommand.get(
            db.IndividualCommand.individual == self.doe.id, db.IndividualCommand.command == "ConfirmLitterSize"
        )
        self.assertEqual((command.before["litter_size6w"], command.after["litter_size6w"]), (5, 3))

    def test_refusals(self):
        litter = self.add()
        for user, count, message in (
            (self.viewer, 3, "Forbidden"),
            (self.other_owner, 3, "Forbidden"),
            (self.owner, 6, "Antal levande vid 6 veckor kan inte vara fler än antal födda."),
            (self.owner, -1, "Antal levande vid 6 veckor kan inte vara fler än antal födda."),
        ):
            with self.subTest(user=user.username, count=count), self.assertRaises(IndividualRefused) as raised:
                confirm_litter_size(user, litter.id, count)
            self.assertEqual(raised.exception.envelope["message"], message)
        self.assertTrue(db.Breeding.get_by_id(litter.id).litter_size6w_preliminary)
        with self.assertRaises(IndividualRefused):
            confirm_litter_size(self.owner, litter.id + 1000, 3)

    def test_wrong_report_year_is_refused(self):
        litter = self.add()
        with self.assertRaises(IndividualRefused):
            confirm_litter_size(self.owner, litter.id, 3, year=2024)
        self.assertEqual(confirm_litter_size(self.owner, litter.id, 3, year=2025).litter_size6w, 3)


class TestLaterCertificate(LitterTest):
    """The litter added without a certificate gets its number with its first certificate (L4, L5)."""

    def setUp(self):
        super().setUp()
        self.litter = self.add()
        self.client.post("/api/login", json={"username": "owner", "password": "pass"})

    def numbered(self, number, born=date(2025, 1, 5)):
        return db.Breeding.create(
            breeding_herd_id=self.g1, birth_date=born, litter_number=number, litter_size=4, litter_size6w=4
        )

    def register(self, paper_number="G1-2551", **fields):
        body = {
            "breeding_id": self.litter.id,
            "sex": "female",
            "color": "bleighe",
            "certificate_type": "paper",
            "paper_certificate": "SC-9",
            "paper_number": paper_number,
            **fields,
        }
        return self.client.post(URL, json=body)

    def state(self):
        litter = db.Breeding.get_by_id(self.litter.id)
        kits = db.Individual.select().where(db.Individual.breeding == self.litter.id).count()
        return litter.litter_number, litter.litter_size6w, litter.litter_size6w_preliminary, kits

    def test_later_certificate_numbers_the_litter(self):
        self.numbered(1)  # the next free number is 2, but the paper says kull 5
        response = self.register()
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["individual"]["number"], "G1-2551")
        self.assertEqual(response.get_json()["breeding"], {"id": self.litter.id, "litter_number": 5, "created": False})
        self.assertEqual(self.state()[0], 5)

    def test_taken_number_goes_to_manager(self):
        self.numbered(5)
        response = self.register(litter_size6w=3)
        self.assertEqual((response.status_code, response.get_json()["title"]), (409, "number_conflict"))
        self.assertEqual({c["kind"] for c in response.get_json()["conflicts"]}, {"litter_order"})
        self.assertEqual(self.state(), (None, 5, True, 0))  # nothing written: not the number, not the count

    def test_a_higher_number_goes_to_manager(self):
        self.numbered(6)
        response = self.register()
        self.assertEqual((response.status_code, response.get_json()["title"]), (409, "number_conflict"))
        self.assertEqual(self.state(), (None, 5, True, 0))

    def test_number_check_handles_an_unnumbered_litter(self):
        self.numbered(1)
        free = self.client.post(f"{URL}/number-check", json={"breeding_id": self.litter.id, "paper_number": "G1-2551"})
        self.assertEqual(
            (free.status_code, free.get_json()["status"], free.get_json()["stamboken_number"]),
            (200, "match", "G1-2551"),
        )
        self.numbered(5, born=date(2025, 2, 1))
        taken = self.client.post(f"{URL}/number-check", json={"breeding_id": self.litter.id, "paper_number": "G1-2551"})
        self.assertEqual((taken.get_json()["status"], taken.get_json()["stamboken_number"]), ("conflict", None))
        self.assertEqual(self.state()[0], None)  # a dry run

    def test_number_from_certificate(self):
        self.numbered(1)
        self.assertEqual(number_from_certificate(self.litter, "G1-2551"), (5, None))
        blocker = self.numbered(5, born=date(2025, 2, 1))
        self.assertEqual(number_from_certificate(self.litter, "G1-2551"), (None, blocker))

    def test_digital_certificate_before_a_numbered_litter_is_refused(self):
        self.numbered(1, born=date(2025, 8, 1))  # born after ours: fitting ours in needs a renumber
        response = self.register(certificate_type="digital", paper_certificate=None, paper_number=None)
        self.assertEqual((response.status_code, response.get_json()["title"]), (409, "litter_order_conflict"))
        self.assertEqual(self.state(), (None, 5, True, 0))

    def test_suggest_number_for_an_unnumbered_litter(self):
        self.numbered(1)
        response = self.client.get(f"{URL}/suggest-number", query_string={"breeding_id": self.litter.id})
        data = response.get_json()
        self.assertEqual((response.status_code, data["suggested"], data["litter_number"]), (200, "G1-2521", 2))
        self.assertEqual((data["breeding_id"], data["can_issue_certificate"]), (self.litter.id, True))

    def test_certificate_count_replaces_preliminary(self):
        self.numbered(1)
        response = self.register(litter_size6w=3)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self.state(), (5, 3, False, 1))

    def test_certificate_count_does_not_replace_a_confirmed_one(self):
        self.numbered(1)
        confirm_litter_size(self.owner, self.litter.id, 4)
        self.assertEqual(self.register(litter_size6w=3).status_code, 201)
        self.assertEqual(self.state()[1:3], (4, False))
