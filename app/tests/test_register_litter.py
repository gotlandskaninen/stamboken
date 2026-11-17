"""
A litter without a certificate (step 4b, Task 1): RegisterLitter and ConfirmLitterSize, and the certificate that
numbers such a litter later. Synthetic herds and rabbits only.

isort:skip_file
"""

import threading
import time
from datetime import date, timedelta
from unittest import mock

import blueprints.individual_v2_create as create
import utils.arsrapport as arsrapport
import utils.data_access as da
import utils.database as db
import utils.individual_commands as ic
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP
from utils.arsrapport import ReportGrant
from utils.herd_tracking import record_herd_tracking
from utils.individual_commands import IndividualRefused, SameLitter, confirm_litter_size, register_litter
from utils.individual_number_v2 import NO_LITTER_NUMBER, number_from_certificate
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

    def test_a_litter_four_to_thirty_four_days_later_is_refused_by_the_35_day_rule(self):
        self.add()
        with self.assertRaises(IndividualRefused) as raised:
            self.add(born=BORN + timedelta(days=10))
        self.assertIn("inom 35 dagar", raised.exception.envelope["message"])
        self.assertNotEqual(self.add(born=BORN + timedelta(days=40)).birth_date, BORN)

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

    @staticmethod
    def waits_for_a(pids):
        """B's own backend, by its pid, waits for the mother's litter lock, and A's backend is what blocks it."""
        if not {"a", "b", "mother"} <= pids.keys():
            return False
        cursor = db.DATABASE.execute_sql(
            "SELECT %s = ANY(pg_blocking_pids(pid)) FROM pg_locks WHERE pid = %s AND locktype = 'advisory'"
            " AND NOT granted AND classid = %s AND objid = %s AND objsubid = 2",
            (pids["a"], pids["b"], ic._LITTER_LOCK, pids["mother"]),
        )
        row = cursor.fetchone()
        return bool(row and row[0])

    def overlap(self, second):
        """
        Transaction A takes the mother's advisory lock and is held there; `second()` runs in B meanwhile.
        Returns (B's outcome, whether B was seen waiting for that lock, blocked by A, while A held it, A's outcome).
        """
        locked, release = threading.Event(), threading.Event()
        real, outcomes, held, threads, pids = ic.lock_mother_litters, {}, [], [], {}

        def hold_after_lock(mother_id):
            # the asking backend's pid, before it may wait: A is the first to ask, B the one after
            pid = db.DATABASE.execute_sql("SELECT pg_backend_pid()").fetchone()[0]
            pids.update({"b" if held else "a": pid, "mother": mother_id})
            real(mother_id)
            if not held:  # only A
                held.append(True)
                locked.set()
                release.wait(30)

        def run(key, work):
            try:
                db.DATABASE.connect(reuse_if_open=True)
                db.DATABASE.execute_sql("SET lock_timeout = '25s'")  # a failure must not hang on a lock
                db.DATABASE.execute_sql("SET statement_timeout = '60s'")
                outcomes[key] = work()
            except Exception as exc:  # noqa: BLE001 — a deadlock or an IntegrityError lands here and fails below
                outcomes[key] = exc
            finally:
                db.DATABASE.close()

        blocked = False
        try:
            # the certificate route and legacy's writers imported the function by name: patched there too, so B is
            # seen on every path
            with (
                mock.patch.object(ic, "lock_mother_litters", side_effect=hold_after_lock),
                mock.patch.object(create, "lock_mother_litters", side_effect=hold_after_lock),
                mock.patch.object(da, "lock_mother_litters", side_effect=hold_after_lock),
            ):
                threads.append(threading.Thread(target=run, args=("a", self.add)))
                threads[0].start()
                self.assertTrue(locked.wait(10), "A never took the lock")
                threads.append(threading.Thread(target=run, args=("b", second)))
                threads[1].start()
                for _ in range(100):  # bounded: B must be in a lock wait before A is let go
                    if self.waits_for_a(pids) or "b" in outcomes:
                        break
                    time.sleep(0.1)
                blocked = self.waits_for_a(pids) and "b" not in outcomes
        finally:
            release.set()
            for thread in threads:
                thread.join(40)
        self.assertFalse(any(thread.is_alive() for thread in threads), "hung or deadlocked")
        return outcomes["b"], blocked, outcomes["a"]

    def test_concurrent_same_litter(self):
        """B waits for A's commit, then gets samma_kull and A's litter: one litter (L3)."""
        refused, blocked, first = self.overlap(lambda: self.add())
        self.assertTrue(blocked, "B was not waiting for the lock while A held it")
        self.assertIsInstance(refused, SameLitter, refused)
        self.assertIsInstance(first, db.Breeding)
        self.assertEqual(refused.envelope["breeding_id"], first.id)
        self.assertEqual(self.litters(), 1)

    def test_concurrent_registrations_across_herds_of_a_doe_that_moved(self):
        """The doe went G1 -> G2 the day after the birth: the lock is hers, not her herd's."""
        record_herd_tracking(self.doe, self.g2, BORN + timedelta(days=1), "TRANSFER", self.owner)

        def register():
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "owner2", "password": "pass"})
            return client.post(URL, json=self.shortcut_body(BORN + timedelta(days=2)))

        response, blocked, first = self.overlap(register)
        self.assertTrue(blocked, "B was not waiting for the lock while A held it")
        self.assertEqual(first.breeding_herd_id.herd, "G1")
        self.assertEqual(response.status_code, 409, response.get_json())  # the number check sees A's litter
        self.assertIn("duplicate_litter", [c["kind"] for c in response.get_json()["conflicts"]])
        self.assertEqual(self.litters(), 1)

    def test_legacy_birth_waits_for_the_mothers_litter_lock(self):
        """Opus L5: a birth on a pending mating takes the mother's lock first and decides its dates under it."""
        mating = db.Breeding.create(
            breeding_herd_id=self.g1, mother=self.doe, father=self.buck, breed_date=BORN - timedelta(days=29)
        )
        form = {"id": mating.id, "date": str(BORN + timedelta(days=2)), "litter_size": 4}
        result, blocked, first = self.overlap(lambda: da.register_birth(form, self.owner.uuid))
        self.assertTrue(blocked, "B was not waiting for the lock while A held it")
        self.assertIsInstance(first, db.Breeding)
        self.assertEqual(result["status"], "error", result)
        self.assertIn("inom 35 dagar", result["message"])
        self.assertIsNone(db.Breeding.get_by_id(mating.id).birth_date)

    def test_legacy_litter_edit_waits_for_the_mothers_litter_lock(self):
        """Opus L5: moving a litter of the mother's next to the new one takes her lock before the litter's."""
        old = db.Breeding.create(
            breeding_herd_id=self.g1,
            mother=self.doe,
            father=self.buck,
            breed_date=BORN - timedelta(days=131),
            birth_date=BORN - timedelta(days=100),
            litter_size=3,
        )
        form = {"id": old.id, "breed_date": str(BORN - timedelta(days=29)), "birth_date": str(BORN + timedelta(days=2))}
        result, blocked, first = self.overlap(lambda: da.update_breeding(form, self.owner.uuid))
        self.assertTrue(blocked, "B was not waiting for the lock while A held it")
        self.assertIsInstance(first, db.Breeding)
        self.assertEqual(result["status"], "error", result)
        self.assertIn("inom 35 dagar", result["message"])
        self.assertEqual(db.Breeding.get_by_id(old.id).birth_date, BORN - timedelta(days=100))

    @staticmethod
    def shortcut_body(born):
        return {
            "mother": "G1-2411",
            "father": "G2-2412",
            "birth_date": str(born),
            "litter_size": 5,
            "litter_size6w": 4,
            "sex": "female",
            "color": "bleighe",
            "certificate_type": "paper",
            "paper_certificate": "SC-2",
            "paper_number": "G1-2511",
        }

    def test_concurrent_certificate_registration_of_a_new_litter(self):
        """The certificate route creating a litter takes the same lock and decides again under it."""

        def register():
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "owner", "password": "pass"})
            return client.post(URL, json=self.shortcut_body(BORN + timedelta(days=2)))

        response, blocked, first = self.overlap(register)
        self.assertTrue(blocked, "B was not waiting for the lock while A held it")
        self.assertIsInstance(first, db.Breeding)
        self.assertEqual(response.status_code, 409, response.get_json())  # the number check sees A's litter
        self.assertIn("duplicate_litter", [c["kind"] for c in response.get_json()["conflicts"]])
        self.assertEqual(self.litters(), 1)
        self.assertFalse(db.Individual.select().where(db.Individual.certificate == "SC-2").exists())


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

    def test_patch_refused_for_certified_litter(self):
        """FC4: a litter with a certified kit is the manager's, whoever asks; nothing changes."""
        litter = self.add()
        db.Individual.create(origin_herd=self.g1, breeding=litter, number="G1-2551", certificate="SC-1")
        for user in (self.owner, self.manager, self.admin):
            with self.subTest(user=user.username), self.assertRaises(IndividualRefused) as raised:
                confirm_litter_size(user, litter.id, 3)
            self.assertEqual(
                raised.exception.envelope["message"], "Kontakta genbanksansvarig för att ändra en kull med intyg."
            )
        after = db.Breeding.get_by_id(litter.id)
        self.assertEqual((after.litter_size6w, after.litter_size6w_preliminary), (5, True))

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

    def test_the_count_cannot_go_below_the_registered_kits_alive_at_6_weeks(self):
        """Opus L6: of four registered kits one died before 6 weeks and one is voided, so 2 is the floor."""
        litter = self.add()
        kits = [db.Individual.create(origin_herd=self.g1, breeding=litter, number=f"G1-259{n}") for n in range(1, 5)]
        db.Individual.update(death_date=BORN + timedelta(days=60)).where(db.Individual.id == kits[1].id).execute()
        db.Individual.update(death_date=BORN + timedelta(days=10)).where(db.Individual.id == kits[2].id).execute()
        db.Individual.update(voided=True).where(db.Individual.id == kits[3].id).execute()
        with self.assertRaises(IndividualRefused) as raised:
            confirm_litter_size(self.owner, litter.id, 1)
        self.assertEqual(
            raised.exception.envelope["message"],
            "Kullen har 2 registrerade ungar som levde vid 6 veckor. Antal levande vid 6 veckor kan inte vara färre.",
        )
        self.assertTrue(db.Breeding.get_by_id(litter.id).litter_size6w_preliminary)
        self.assertEqual(confirm_litter_size(self.owner, litter.id, 2).litter_size6w, 2)

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
        self.assertEqual({c["kind"] for c in response.get_json()["conflicts"]}, {"litter_number_taken"})
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

    def test_taken_number_has_its_own_action_text(self):
        self.numbered(5)
        check = self.client.post(f"{URL}/number-check", json={"breeding_id": self.litter.id, "paper_number": "G1-2551"})
        action = check.get_json()["actions"][0]
        self.assertEqual(action["text"], "Kullnummer 5 finns redan för 2025. Genbanksansvarig rättar numret.")
        self.numbered(7, born=date(2025, 2, 1))
        higher = self.client.post(
            f"{URL}/number-check", json={"breeding_id": self.litter.id, "paper_number": "G1-2561"}
        )
        self.assertEqual(
            higher.get_json()["actions"][0]["text"],
            "Kull 7 finns redan för 2025 och har ett högre nummer än 6. Genbanksansvarig rättar numret.",
        )

    def test_a_paper_litter_number_of_zero_is_refused(self):
        """G1-2501 reads as litter 0: no match, nothing written (the litter numbers start at 1)."""
        check = self.client.post(f"{URL}/number-check", json={"breeding_id": self.litter.id, "paper_number": "G1-2501"})
        data = check.get_json()
        self.assertEqual((data["status"], data["stamboken_number"]), ("conflict", None))
        self.assertEqual([c["kind"] for c in data["conflicts"]], ["litter_number_invalid"])
        response = self.register(paper_number="G1-2501", litter_size6w=3)
        self.assertEqual((response.status_code, response.get_json()["title"]), (409, "number_conflict"))
        self.assertEqual(self.state(), (None, 5, True, 0))

    def test_a_paper_number_out_of_birth_order_goes_to_manager(self):
        """Opus M1: kull 1 in January and kull 2 in August; the paper of our May litter says kull 3, which would put it
        after a litter born later. The manager renumbers, and nothing is written."""
        self.numbered(1)
        later = self.numbered(2, born=date(2025, 8, 1))
        self.assertEqual(number_from_certificate(self.litter, "G1-2531"), (None, later))
        response = self.register(paper_number="G1-2531", litter_size6w=3)
        problem = response.get_json()
        self.assertEqual((response.status_code, problem["title"]), (409, "number_conflict"))
        self.assertEqual([c["kind"] for c in problem["conflicts"]], ["litter_number_taken"])
        self.assertEqual(
            problem["actions"][0]["text"],
            "Kull 2 finns redan för 2025 och är född efter den här kullen, men har ett lägre nummer än 3. "
            "Genbanksansvarig rättar numret.",
        )
        self.assertEqual(self.state(), (None, 5, True, 0))

    def test_an_old_unnumbered_litter_with_a_rabbit_keeps_the_400(self):
        """Opus L1: only a litter without rabbits numbers itself; an older one without a number keeps the refusal."""
        db.Individual.create(origin_herd=self.g1, breeding=self.litter, number="G1-2599")
        self.numbered(1)
        response = self.register()
        self.assertEqual((response.status_code, response.get_json()["detail"]), (400, NO_LITTER_NUMBER))
        suggestion = self.client.get(f"{URL}/suggest-number", query_string={"breeding_id": self.litter.id})
        self.assertEqual((suggestion.status_code, suggestion.get_json()["detail"]), (400, NO_LITTER_NUMBER))
        check = self.client.post(f"{URL}/number-check", json={"breeding_id": self.litter.id, "paper_number": "G1-2551"})
        self.assertEqual((check.get_json()["status"], check.get_json()["stamboken_number"]), ("uncomputable", None))
        self.assertEqual(self.state(), (None, 5, True, 1))

    def test_suggest_number_knows_a_full_litter(self):
        db.Breeding.update(litter_size6w=0).where(db.Breeding.id == self.litter.id).execute()
        data = self.client.get(f"{URL}/suggest-number", query_string={"breeding_id": self.litter.id}).get_json()
        self.assertEqual(
            (data["can_issue_certificate"], data["certificate_blocked_reason"]), (False, "certificate_quota_exceeded")
        )

    def test_a_digital_registration_keeps_the_chosen_position(self):
        response = self.register(certificate_type="digital", paper_certificate=None, paper_number=None, position=3)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["individual"]["number"], "G1-2513")

    def test_an_out_of_range_position_is_refused_and_writes_nothing(self):
        for position in (0, 10):
            with self.subTest(position=position):
                response = self.register(
                    certificate_type="digital", paper_certificate=None, paper_number=None, position=position
                )
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(self.state(), (None, 5, True, 0))


class TestPromotionNumbersTheLitter(LitterTest):
    """The roster's promotion gives a litter added without a certificate its number, as a registration does."""

    BORN_2026 = date(2026, 5, 10)

    def setUp(self):
        super().setUp()

        class Frozen(date):  # the current-year gate of the promotion must bite whenever the tests run
            @classmethod
            def today(cls):
                return date(2026, 11, 16)

        patcher = mock.patch("blueprints.bunny_v2.date", Frozen)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.litter = self.add(born=self.BORN_2026)
        self.client.post("/api/login", json={"username": "owner", "password": "pass"})
        self.bunnies = [
            db.Bunny.create(breeding=self.litter, slot_order=n, observed_sex="female", observed_color="bleighe")
            for n in (1, 2)
        ]

    def promote(self, bunny, paper_number, **fields):
        body = {"certificate_type": "paper", "paper_certificate": f"SC-{paper_number}", "paper_number": paper_number}
        return self.client.post(f"/api/v2/bunny/{bunny.id}/promote", json={**body, **fields})

    def state(self):
        litter = db.Breeding.get_by_id(self.litter.id)
        return litter.litter_number, litter.litter_size6w, litter.litter_size6w_preliminary

    def test_the_certificates_count_replaces_a_preliminary_one(self):
        response = self.promote(self.bunnies[0], "G1-2661", litter_size6w=3)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self.state(), (6, 3, False))

    def test_a_refusal_after_the_count_rolls_it_back(self):
        db.Breeding.create(breeding_herd_id=self.g1, birth_date=date(2026, 2, 1), litter_number=6, litter_size=4)
        response = self.promote(self.bunnies[0], "G1-2661", litter_size6w=3)
        self.assertEqual((response.status_code, response.get_json()["title"]), (409, "number_conflict"))
        self.assertEqual(self.state(), (None, 5, True))

    def test_a_preliminary_count_is_shown_as_such_and_the_certificate_confirms_it(self):
        """
        Round 2: the litter list tells the dialogs the count is preliminary, so they ask for it; the certificate's
        count replaces it, and the litter is then confirmed for good (ConfirmLitterSize refuses a certified litter).
        """

        def listed():
            breedings = self.client.get("/api/breeding/G1").get_json()["breedings"]
            return next(b for b in breedings if b["id"] == self.litter.id)

        self.assertEqual((listed()["litter_size6w"], listed()["litter_size6w_preliminary"]), (5, True))
        response = self.promote(self.bunnies[0], "G1-2661", litter_size6w=3)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual((listed()["litter_size6w"], listed()["litter_size6w_preliminary"]), (3, False))
        with self.assertRaises(IndividualRefused) as refused:
            confirm_litter_size(self.owner, self.litter.id, 4)
        self.assertEqual(refused.exception.envelope["message"], ic.CERTIFIED_LITTER)

    def test_an_unnumbered_litter_with_a_rabbit_is_not_numbered_by_promotion(self):
        """Opus L1: the roster's promotion keeps the old 400 for a litter without a number that has a rabbit."""
        db.Individual.create(origin_herd=self.g1, breeding=self.litter, number="G1-2699")
        response = self.promote(self.bunnies[0], "G1-2661", litter_size6w=3)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (400, NO_LITTER_NUMBER))
        self.assertEqual(self.state(), (None, 5, True))

    def test_the_register_buttons_check_tolerates_the_paper_gap(self):
        """Round 2: after paper litter 6 (litter 1 exists), the button's check-order passes as promotion does."""
        db.Breeding.create(
            breeding_herd_id=self.g1, birth_date=date(2026, 1, 10), litter_number=1, litter_size=4, litter_size6w=4
        )
        self.assertEqual(self.promote(self.bunnies[0], "G1-2661").status_code, 201)
        check = "/api/v2/breeding/check-order?herd=G1&year=2026"
        self.assertTrue(self.client.get(f"{check}&allow_gaps=1").get_json()["consistent"])
        self.assertFalse(self.client.get(check).get_json()["consistent"])  # the renumber view keeps its own rule

    def test_two_promotions_in_the_current_year_after_a_paper_gap(self):
        """Litter 1 exists, the paper says 6: the next sibling is not stopped by the consecutive-number gate."""
        db.Breeding.create(
            breeding_herd_id=self.g1, birth_date=date(2026, 1, 10), litter_number=1, litter_size=4, litter_size6w=4
        )
        first = self.promote(self.bunnies[0], "G1-2661")
        second = self.promote(self.bunnies[1], "G1-2662")
        self.assertEqual((first.status_code, second.status_code), (201, 201), (first.get_json(), second.get_json()))
        self.assertEqual(self.state()[0], 6)
