#!/usr/bin/env python3
"""
"Kullar under Y" in the report (step 4b, Task 2): a litter without a certificate is added, confirmed or changed
through the report's endpoints, by a login, by a link and by a helper on a paper form. Synthetic data only.

isort:skip_file
"""

from datetime import date, datetime, timedelta
from datetime import time as clock
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from utils.individual_commands import LITTER_CHANGED, IndividualRefused

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row
from tests.inbox_fixtures import QUALITY

NOW = datetime.combine(date(2026, 1, 15), clock(12), arsrapport.STOCKHOLM)
BORN = "2025-05-10"
REPORT = "/besattning/G9001/2025"


class LitterApiTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(NOW)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.h2 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        self.doe, self.buck, self.doe2 = self.rabbits(self.h, 3)  # female, male, female
        self.other_doe = self.rabbits(self.h2, 1)[0]

    def open_link(self):
        response = self.client.post("/api/v2/rapport/oppna", json={"token": mail.link_token("rapport", self.code.id)})
        self.assertEqual(response.status_code, 200)

    def litter(self, mother=None, father=None, born=BORN, size=5, size6w=None, path=REPORT):
        return self.api(
            "POST",
            f"{path}/kull",
            mother_id=(mother or self.doe).id,
            father_id=(father or self.buck).id,
            birth_date=born,
            litter_size=size,
            litter_size6w=size6w,
        )

    def litters(self):
        return (
            db.Breeding.select().where(db.Breeding.mother == self.doe.id, db.Breeding.litter_number.is_null()).count()
        )

    def body_for(self):
        """Every rabbit of the herd's list kept."""
        return self.body(*[self.kvar(rabbit, vikt=2.8) for rabbit in (self.doe, self.buck, self.doe2)])


class TestAddLitter(LitterApiTest):
    def test_add_litter_from_report_counts_for_support(self):
        self.assertFalse(arsrapport.herd_conditions(self.h, self.round_, None)["kull"])
        self.login("owner")
        response = self.litter()
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        data = response.get_json()
        (row,) = data["litters"]
        self.assertEqual(row["id"], data["id"])
        self.assertEqual(
            (
                row["mother"],
                row["father"],
                row["birth_date"],
                row["litter_size"],
                row["litter_size6w"],
                row["preliminary"],
            ),
            (self.doe.number, self.buck.number, BORN, 5, 5, True),
        )
        self.assertTrue(arsrapport.herd_conditions(self.h, self.round_, None)["kull"])
        self.assertEqual(self.api("GET", REPORT).get_json()["litters"], data["litters"])

    def test_a_given_count_is_confirmed_from_the_start(self):
        self.login("owner")
        (row,) = self.litter(size6w=3).get_json()["litters"]
        self.assertEqual((row["litter_size6w"], row["preliminary"]), (3, False))

    def test_litter_survives_withdraw(self):
        """Review focus 1: through the link, the report is withdrawn, the litter stays and the receipt lists it."""
        self.open_link()
        self.assertEqual(self.litter().status_code, 201)
        sent = self.api("POST", f"{REPORT}/skicka", **self.body_for())
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        (mail_row,) = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.kvitto")
        kvitto = arsrapport._kvitto(mail_row.params)
        self.assertEqual(kvitto["kullar"], [f"efter {self.doe.number} född {BORN}, 5 födda"])
        _, text = mail.render("arsrapport.kvitto", kvitto)
        self.assertIn("De finns kvar även om du drar tillbaka rapporten.", text)
        report = db.YearlyHerdReport.get()
        out = self.api("POST", f"{REPORT}/dra-tillbaka", revision=report.revision, reason=None)
        self.assertEqual(out.status_code, 200, out.get_data(as_text=True))
        self.assertEqual(self.litters(), 1)
        self.assertEqual(len(self.api("GET", REPORT).get_json()["litters"]), 1)
        command = db.IndividualCommand.get(db.IndividualCommand.command == "RegisterLitter")
        self.assertEqual(command.access_code_id, self.code.id)

    def test_a_litter_moves_no_received_at(self):
        """L7: no correction, so the report keeps its first-submission time and its revision."""
        self.login("owner")
        sent = self.api("POST", f"{REPORT}/skicka", **self.body_for())
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        before = db.YearlyHerdReport.get()
        self.at(NOW + timedelta(days=3))
        self.assertEqual(self.litter().status_code, 201)
        after = db.YearlyHerdReport.get()
        self.assertEqual(
            (after.received_at, after.revision, after.status), (before.received_at, before.revision, "submitted")
        )
        self.assertEqual(db.YearlyReportSubmission.select().count(), 1)
        self.assertTrue(arsrapport.herd_conditions(self.h, self.round_, after)["kull"])

    def test_paper_helper_adds_litter_through_item(self):
        stored = [(f"inkorg/original/{n}.jpg", f"{self.h.id}{n}".rjust(64, "0"), QUALITY) for n in range(1)]
        item, (document,) = inbox.create_upload(self.owner, self.h, None, stored)
        document.doc_type = "arsblankett"
        document.save()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        self.assertEqual(self.litter().status_code, 403)  # not through the item: the helper has no right of her own
        response = self.client.post(
            f"/api/v2/arsrapport{REPORT}/kull?post={item.id}",
            json={
                "mother_id": self.doe.id,
                "father_id": self.buck.id,
                "birth_date": BORN,
                "litter_size": 4,
                "litter_size6w": 4,
            },
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        self.assertEqual(self.litters(), 1)
        command = db.IndividualCommand.get(db.IndividualCommand.command == "RegisterLitter")
        self.assertEqual(command.actor_id, self.helper.id)
        self.assertTrue(
            db.InboxOperation.select().where(db.InboxOperation.operation_id == command.operation_id).exists()
        )

    def test_a_helper_without_the_item_is_refused(self):
        self.login("hjalp")
        other = self.client.post(f"/api/v2/arsrapport{REPORT}/kull?post=999", json={})
        self.assertEqual(other.status_code, 403)
        self.assertEqual(self.litters(), 0)


class TestSameLitter(LitterApiTest):
    def test_samma_kull_is_409_with_the_litter_and_patch_changes_its_counts(self):
        self.login("owner")
        first = self.litter().get_json()["id"]
        again = self.litter(born="2025-05-12", size=6, size6w=4)
        self.assertEqual(again.status_code, 409)
        problem = again.get_json()
        self.assertEqual((problem["code"], problem["breeding_id"]), ("samma_kull", first))
        self.assertTrue(problem["detail"].startswith("Modern har redan en kull"))
        self.assertEqual(self.litters(), 1)
        changed = self.api("PATCH", f"{REPORT}/kull/{first}", litter_size=6, litter_size6w=4)
        self.assertEqual(changed.status_code, 200, changed.get_data(as_text=True))
        (row,) = changed.get_json()["litters"]
        self.assertEqual((row["litter_size"], row["litter_size6w"], row["preliminary"]), (6, 4, False))

    def test_patch_with_an_empty_count_keeps_it_preliminary(self):
        self.login("owner")
        first = self.litter(size6w=2).get_json()["id"]
        (row,) = self.api("PATCH", f"{REPORT}/kull/{first}", litter_size=6, litter_size6w=None).get_json()["litters"]
        self.assertEqual((row["litter_size"], row["litter_size6w"], row["preliminary"]), (6, 6, True))

    def test_confirm_clears_preliminary_through_the_link(self):
        self.open_link()
        first = self.litter().get_json()["id"]
        done = self.api("PATCH", f"{REPORT}/kull/{first}", litter_size6w=3)
        self.assertEqual(done.status_code, 200, done.get_data(as_text=True))
        (row,) = done.get_json()["litters"]
        self.assertEqual((row["litter_size"], row["litter_size6w"], row["preliminary"]), (5, 3, False))
        high = self.api("PATCH", f"{REPORT}/kull/{first}", litter_size6w=9)
        self.assertEqual(high.status_code, 422)

    def test_patch_refused_for_certified_litter(self):
        """FC4: a litter with a certified kit is the manager's; nothing changes."""
        self.login("owner")
        first = self.litter().get_json()["id"]
        db.Individual.create(origin_herd=self.h, breeding=first, number="G9001-2551", certificate="SC-1")
        refused = self.api("PATCH", f"{REPORT}/kull/{first}", litter_size6w=3)
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(refused.get_json()["detail"], "Kontakta genbanksansvarig för att ändra en kull med intyg.")
        self.assertTrue(db.Breeding.get_by_id(first).litter_size6w_preliminary)

    def test_patch_of_another_herds_litter_is_a_404(self):
        self.login("owner")
        other = db.Breeding.create(
            breeding_herd_id=self.h2, mother=self.other_doe, birth_date=date(2025, 5, 1), litter_size=4, litter_size6w=4
        )
        self.assertEqual(self.api("PATCH", f"{REPORT}/kull/{other.id}", litter_size6w=1).status_code, 404)
        self.assertEqual(db.Breeding.get_by_id(other.id).litter_size6w, 4)


class TestLitterRights(LitterApiTest):
    def test_a_link_writes_only_in_its_own_herd(self):
        self.open_link()
        other = self.litter(mother=self.other_doe, path="/besattning/G9002/2025")
        self.assertIn(other.status_code, (403, 404))
        stranger = self.litter(mother=self.other_doe)  # her herd is not the link's
        self.assertEqual(stranger.status_code, 422)
        self.assertEqual(db.Breeding.select().where(db.Breeding.mother == self.other_doe.id).count(), 0)

    def test_a_link_cannot_add_a_litter_of_another_year(self):
        self.open_link()
        self.assertEqual(self.litter(born="2024-05-10").status_code, 422)

    def test_a_revoked_link_is_refused(self):
        self.open_link()
        report_code.revoke(self.code, now=arsrapport.now())
        response = self.litter()
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "lank_ogiltig"))
        self.assertEqual(self.litters(), 0)

    def test_no_session_is_a_401(self):
        self.assertEqual(self.litter().status_code, 401)

    def test_a_login_without_a_right_is_refused(self):
        self.login("hjalp")
        self.assertEqual(self.litter().status_code, 403)

    def test_a_closed_round_is_refused(self):
        self.login("owner")
        self.at(NOW + timedelta(days=200))
        response = self.litter()
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "rundan_stangd"))
        self.assertEqual(self.litters(), 0)

    def test_a_bad_body_is_a_400(self):
        self.login("owner")
        for field, value in (("litter_size", "5"), ("mother_id", True), ("birth_date", "igår"), ("litter_size6w", 1.5)):
            body = {
                "mother_id": self.doe.id,
                "father_id": self.buck.id,
                "birth_date": BORN,
                "litter_size": 5,
                "litter_size6w": None,
                field: value,
            }
            with self.subTest(field=field):
                response = self.api("POST", f"{REPORT}/kull", **body)
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        extra = self.api("POST", f"{REPORT}/kull", mother_id=1, father_id=2, birth_date=BORN, litter_size=1, number=3)
        self.assertEqual(extra.status_code, 400)
        self.assertEqual(self.litters(), 0)


class TestFathers(LitterApiTest):
    def test_a_link_gets_the_genebanks_living_males_and_nothing_else(self):
        castrated = self.rabbits(self.h, 1, sexes=("male",))[0]
        castrated.castration_date = date(2025, 1, 1)
        castrated.save()
        dead_before = self.rabbits(self.h2, 1, sexes=("male",))[0]
        dead_before.death_date = date(2024, 11, 1)  # before any mating of a 2025 litter
        dead_before.save()
        elsewhere = db.Herd.create(genebank=self.mellerud, herd="M9001", is_active=True)
        self.rabbits(elsewhere, 1, sexes=("male",))
        in_other_herd = self.rabbits(self.h2, 1, sexes=("male",))[0]
        self.open_link()
        response = self.api("GET", f"{REPORT}/hanar")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        males = response.get_json()["hanar"]
        # a castrated male is offered too: the register accepts him as a father
        self.assertEqual(
            [m["number"] for m in males], sorted([self.buck.number, in_other_herd.number, castrated.number])
        )
        self.assertEqual({tuple(sorted(m)) for m in males}, {("id", "name", "number")})

    def test_a_father_who_died_in_december_can_sire_a_january_litter(self):
        """A litter born 10 January 2025 was mated around 10 December 2024: the father may have died after that."""
        december = self.rabbits(self.h2, 1, sexes=("male",))[0]
        december.death_date = date(2024, 12, 20)
        december.save()
        self.open_link()
        males = [m["number"] for m in self.api("GET", f"{REPORT}/hanar").get_json()["hanar"]]
        self.assertIn(december.number, males)
        response = self.litter(father=december, born="2025-01-10")
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))

    def test_a_castrated_father_is_offered_and_accepted(self):
        self.buck.castration_date = date(2025, 1, 1)
        self.buck.save()
        self.login("owner")
        self.assertIn(self.buck.number, [m["number"] for m in self.api("GET", f"{REPORT}/hanar").get_json()["hanar"]])
        self.assertEqual(self.litter().status_code, 201)

    def test_the_father_list_needs_a_session_for_the_herd(self):
        self.assertEqual(self.api("GET", f"{REPORT}/hanar").status_code, 401)
        self.login("hjalp")
        self.assertEqual(self.api("GET", f"{REPORT}/hanar").status_code, 403)


class TestMothers(LitterApiTest):
    def test_a_doe_sold_after_her_litter_can_be_chosen_and_the_litter_saved(self):
        """Review 4: a litter of May is added in the autumn, when the doe is no longer on the report's list."""
        ht_row("TRANSFER", from_herd=self.h, herd=self.h2, individual=self.doe2, herd_tracking_date=date(2025, 8, 1))
        self.open_link()
        self.assertNotIn(self.doe2.id, [r["id"] for r in self.api("GET", REPORT).get_json()["rabbits"]])
        response = self.api("GET", f"{REPORT}/honor")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        does = response.get_json()["honor"]
        self.assertIn(self.doe2.id, [d["id"] for d in does])
        self.assertEqual({tuple(sorted(d)) for d in does}, {("id", "name", "number")})
        self.assertNotIn(self.other_doe.id, [d["id"] for d in does])
        self.assertNotIn(self.buck.id, [d["id"] for d in does])
        saved = self.litter(mother=self.doe2)
        self.assertEqual(saved.status_code, 201, saved.get_data(as_text=True))

    def test_a_doe_that_died_before_the_year_is_not_offered(self):
        self.doe2.death_date = date(2024, 12, 1)
        self.doe2.save()
        self.login("owner")
        self.assertNotIn(self.doe2.id, [d["id"] for d in self.api("GET", f"{REPORT}/honor").get_json()["honor"]])

    def test_only_does_held_in_the_year_are_offered(self):
        """Opus L8: a doe that left the herd before the year is not offered, born here or not; one held on 1 January,
        one that came during the year and one born here without any herd-tracking row are."""
        born_gone, sold_in_year = self.rabbits(self.h, 2, born=date(2023, 5, 1), sexes=("female",))
        gone = self.rabbits(self.h2, 1, born=date(2023, 3, 1), sexes=("female",))[0]
        ht_row("TRANSFER", from_herd=self.h2, herd=self.h, individual=gone, herd_tracking_date=date(2023, 8, 1))
        for doe in (gone, born_gone):
            ht_row("TRANSFER", from_herd=self.h, herd=self.h2, individual=doe, herd_tracking_date=date(2024, 6, 1))
        ht_row("TRANSFER", from_herd=self.h, herd=self.h2, individual=sold_in_year, herd_tracking_date=date(2025, 3, 1))
        came = self.rabbits(self.h2, 1, born=date(2024, 3, 1), sexes=("female",))[0]
        ht_row("TRANSFER", from_herd=self.h2, herd=self.h, individual=came, herd_tracking_date=date(2025, 6, 1))
        late = self.rabbits(self.h2, 1, born=date(2024, 3, 1), sexes=("female",))[0]
        ht_row("TRANSFER", from_herd=self.h2, herd=self.h, individual=late, herd_tracking_date=date(2026, 1, 2))
        untracked = db.Individual.create(
            origin_herd=self.h, breeding=self.doe.breeding, number="G9001-2499", sex="female"
        )
        self.login("owner")
        offered = {d["id"] for d in self.api("GET", f"{REPORT}/honor").get_json()["honor"]}
        self.assertEqual(offered, {self.doe.id, self.doe2.id, sold_in_year.id, came.id, untracked.id})

    def test_the_mother_list_needs_a_session_for_the_herd(self):
        self.assertEqual(self.api("GET", f"{REPORT}/honor").status_code, 401)
        self.login("hjalp")
        self.assertEqual(self.api("GET", f"{REPORT}/honor").status_code, 403)


class TestKitsAndMoves(LitterApiTest):
    def test_the_born_count_cannot_drop_below_the_kits(self):
        self.login("owner")
        first = self.litter(size=5, size6w=5).get_json()["id"]
        for k in range(4):
            db.Individual.create(origin_herd=self.h, breeding=first, number=f"G9001-25{k}1")
        kit = db.Individual.create(origin_herd=self.h, breeding=first, number="G9001-2591")
        db.Bunny.create(breeding=first, slot_order=1, fate="registered", individual=kit)  # linked: not counted twice
        low = self.api("PATCH", f"{REPORT}/kull/{first}", litter_size=2, litter_size6w=2)
        self.assertEqual(low.status_code, 422)
        self.assertEqual(
            low.get_json()["detail"], "Kullen har redan 5 ungar i registret. Antal födda kan inte vara färre."
        )
        self.assertEqual(db.Breeding.get_by_id(first).litter_size, 5)
        # five registered kits alive: five at 6 weeks too (ConfirmLitterSize's floor)
        self.assertEqual(self.api("PATCH", f"{REPORT}/kull/{first}", litter_size=5, litter_size6w=5).status_code, 200)

    def test_unlinked_roster_slots_count_as_kits(self):
        self.login("owner")
        first = self.litter(size=4, size6w=4).get_json()["id"]
        for slot in range(3):
            db.Bunny.create(breeding=first, slot_order=slot)
        self.assertEqual(self.api("PATCH", f"{REPORT}/kull/{first}", litter_size=2, litter_size6w=2).status_code, 422)
        self.assertEqual(self.api("PATCH", f"{REPORT}/kull/{first}", litter_size=3, litter_size6w=2).status_code, 200)

    def test_a_litter_moved_between_the_check_and_the_command_is_not_changed(self):
        """Review 2: a helper through a form; a manager moves the litter to G9002 before the command runs."""
        self.owner.add_role("owner", self.h.id)
        self.login("owner")
        first = self.litter(size=5, size6w=None).get_json()["id"]
        stored = [(f"inkorg/original/{n}.jpg", f"{self.h.id}{n}".rjust(64, "0"), QUALITY) for n in range(1)]
        item, (document,) = inbox.create_upload(self.owner, self.h, None, stored)
        document.doc_type = "arsblankett"
        document.save()
        inbox.take(item, self.helper, over=False)
        real = arsrapport._lock_form

        def locked_then_moved(*args):
            result = real(*args)
            db.Breeding.update(breeding_herd_id=self.h2.id).where(db.Breeding.id == first).execute()
            return result

        self.login("hjalp")
        with mock.patch.object(arsrapport, "_lock_form", side_effect=locked_then_moved):
            response = self.client.patch(
                f"/api/v2/arsrapport{REPORT}/kull/{first}?post={item.id}", json={"litter_size6w": 3}
            )
        self.assertEqual(response.status_code, 404, response.get_data(as_text=True))
        litter = db.Breeding.get_by_id(first)
        self.assertEqual((litter.litter_size6w, litter.litter_size6w_preliminary), (5, True))


class TestAddedReceipt(LitterApiTest):
    def test_each_litter_added_through_the_report_gets_a_receipt(self):
        """Spec 5.8 (Opus L2): one receipt per litter added, by a link or an account; none for a changed count."""
        self.open_link()
        first = self.litter().get_json()["id"]
        (row,) = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kull")
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.params, (row.ref_type, row.ref_id), row.priority),
            ("member", self.member.id, {"breeding_id": first}, ("breeding", first), 0),
        )
        self.assertEqual(row.dedupe_key, f"arsrapport.ny_kull:{first}")
        subject, body = mail.render("arsrapport.ny_kull", mail.MAIL_KINDS["arsrapport.ny_kull"].build(row.params))
        self.assertEqual(subject, "En kull är registrerad i G9001")
        self.assertIn(
            f"Kullen efter {self.doe.number} född {BORN} är registrerad i Stamboken för besättning G9001. Den lades "
            "till i årsrapporten. Den finns kvar även om du drar tillbaka rapporten.",
            body,
        )
        self.assertEqual(self.api("PATCH", f"{REPORT}/kull/{first}", litter_size6w=3).status_code, 200)
        self.login("owner")
        second = self.litter(born="2025-08-20").get_json()["id"]
        rows = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kull").order_by(db.MailMessage.id)
        self.assertEqual([row.params["breeding_id"] for row in rows], [first, second])

    def test_a_refused_litter_gets_no_receipt(self):
        self.login("owner")
        self.assertEqual(self.litter(size=0).status_code, 422)
        self.assertEqual(self.litter(born="2027-01-01").status_code, 422)
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kull").exists())

    def test_a_deleted_litter_cancels_its_receipt(self):
        self.login("owner")
        first = self.litter().get_json()["id"]
        db.Breeding.delete().where(db.Breeding.id == first).execute()
        self.assertIsNone(mail.MAIL_KINDS["arsrapport.ny_kull"].build({"breeding_id": first}))


class TestReceiptSnapshot(LitterApiTest):
    def test_the_receipt_mail_kinds_build(self):
        """Review P1: the mail worker calls the registered builder with the row's params."""
        self.open_link()
        self.litter()
        self.assertEqual(self.api("POST", f"{REPORT}/skicka", **self.body_for()).status_code, 200)
        (row,) = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.kvitto")
        for kind in ("arsrapport.kvitto", "arsrapport.andrad"):
            variables = mail.MAIL_KINDS[kind].build(row.params)
            self.assertEqual(variables["kullar"], [f"efter {self.doe.number} född {BORN}, 5 födda"])

    def test_a_corrected_mother_keeps_the_litter_on_the_receipt(self):
        """The litter is found by the id its command made, not by the mother it ran on."""
        self.login("owner")
        litter_id = self.litter().get_json()["id"]
        db.Breeding.update(mother=self.doe2).where(db.Breeding.id == litter_id).execute()  # corrected before Skicka
        self.assertEqual(self.api("POST", f"{REPORT}/skicka", **self.body_for()).status_code, 200)
        submission = db.YearlyReportSubmission.get()
        self.assertEqual([item["id"] for item in submission.data["litters_added"]], [litter_id])
        self.assertEqual(
            arsrapport._kvitto({"submission_id": submission.id})["kullar"],
            [f"efter {self.doe2.number} född {BORN}, 5 födda"],
        )

    def test_a_litter_after_the_submission_is_the_next_ones_and_later_edits_leave_the_receipt(self):
        self.login("owner")
        first_litter = self.litter().get_json()["id"]
        self.assertEqual(self.api("POST", f"{REPORT}/skicka", **self.body_for()).status_code, 200)
        first = db.YearlyReportSubmission.get()
        self.assertEqual([item["id"] for item in first.data["litters_added"]], [first_litter])
        self.assertEqual(self.litter(self.doe2, born="2025-06-20").status_code, 201)
        self.api("PATCH", f"{REPORT}/kull/{first_litter}", litter_size=7, litter_size6w=6)
        self.assertEqual(len(arsrapport._kvitto({"submission_id": first.id})["kullar"]), 1)
        self.assertIn("5 födda", arsrapport._kvitto({"submission_id": first.id})["kullar"][0])
        body = {**self.body_for(), "revision": db.YearlyHerdReport.get().revision}
        self.assertEqual(self.api("POST", f"{REPORT}/skicka", **body).status_code, 200)
        second = db.YearlyReportSubmission.select().order_by(db.YearlyReportSubmission.id.desc()).first()
        self.assertEqual(
            arsrapport._kvitto({"submission_id": second.id})["kullar"],
            [f"efter {self.doe2.number} född 2025-06-20, 5 födda"],
        )


class TestPreliminaryMark(LitterApiTest):
    def test_statistik_and_status_mark_a_preliminary_count(self):
        """L7: the support statistics, and the status row, say the 6-week count is a guess until it is confirmed."""
        self.login("owner")
        first = self.litter().get_json()["id"]
        stat = arsrapport.statistik(self.gotland.id, 2025)[self.h.id]
        self.assertEqual((stat.levande_6v, stat.preliminart), (5, True))
        row = self.status_row()
        self.assertTrue(row["statistik"]["preliminart"])
        self.api("PATCH", f"{REPORT}/kull/{first}", litter_size6w=4)
        stat = arsrapport.statistik(self.gotland.id, 2025)[self.h.id]
        self.assertEqual((stat.levande_6v, stat.preliminart), (4, False))
        self.assertFalse(self.status_row()["statistik"]["preliminart"])

    def status_row(self):
        view = arsrapport.status_view(self.round_, self.gotland.id)
        return next(row for row in view["rows"] if row["herd"] == "G9001")

    def test_a_herd_without_litters_is_not_preliminary(self):
        self.assertFalse(self.status_row()["statistik"]["preliminart"])


class TestMinBesattning(LitterApiTest):
    def test_confirm_the_count_from_my_herd(self):
        self.login("owner")
        first = self.litter().get_json()["id"]
        done = self.client.post(f"/api/v2/breeding/{first}/antal", json={"litter_size6w": 3})
        self.assertEqual(done.status_code, 200, done.get_data(as_text=True))
        litter = db.Breeding.get_by_id(first)
        self.assertEqual((litter.litter_size6w, litter.litter_size6w_preliminary), (3, False))
        self.assertEqual(
            self.client.post(f"/api/v2/breeding/{first}/antal", json={"litter_size6w": 99}).status_code, 422
        )
        self.assertEqual(
            self.client.post(f"/api/v2/breeding/{first}/antal", json={"litter_size6w": "3"}).status_code, 400
        )
        self.assertEqual(self.client.post("/api/v2/breeding/99999/antal", json={"litter_size6w": 1}).status_code, 404)
        self.login("hjalp")
        self.assertEqual(
            self.client.post(f"/api/v2/breeding/{first}/antal", json={"litter_size6w": 2}).status_code, 404
        )
        self.assertEqual(db.Breeding.get_by_id(first).litter_size6w, 3)

    def test_without_a_right_every_litter_reads_as_missing(self):
        """Opus L3: an absent litter, one without a birth and one of the herd's read the same to someone without a
        right to them, and its owner hears what is wrong."""
        mating = db.Breeding.create(
            breeding_herd_id=self.h, mother=self.doe, father=self.buck, breed_date=date(2025, 1, 2)
        )
        self.login("owner")
        first = self.litter().get_json()["id"]
        no_birth = self.client.post(f"/api/v2/breeding/{mating.id}/antal", json={"litter_size6w": 2})
        self.assertEqual(
            (no_birth.status_code, no_birth.get_json()["detail"]), (422, "Kullen har ingen födelse registrerad.")
        )
        self.login("hjalp")
        answers = [
            self.client.post(f"/api/v2/breeding/{breeding_id}/antal", json={"litter_size6w": 2})
            for breeding_id in (mating.id, first, mating.id + 100000)
        ]
        self.assertEqual(
            {(a.status_code, a.get_data(as_text=True)) for a in answers},
            {(answers[0].status_code, answers[0].get_data(as_text=True))},
        )
        self.assertEqual((answers[0].status_code, answers[0].get_json()["detail"]), (404, "Kullen finns inte."))

    def test_a_litter_changed_meanwhile_is_a_conflict(self):
        """Opus L3: the command's 409 reaches both callers as a 409."""
        refused = IndividualRefused(LITTER_CHANGED)
        self.assertEqual(arsrapport._litter_refused(refused).status, 409)
        self.login("owner")
        first = self.litter().get_json()["id"]
        with mock.patch("blueprints.breeding.confirm_litter_size", side_effect=refused):
            response = self.client.post(f"/api/v2/breeding/{first}/antal", json={"litter_size6w": 2})
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, LITTER_CHANGED))

    def test_an_unknown_mother_is_a_404(self):
        """Opus L3: a mother id that is no rabbit is not found, not a 500."""
        self.login("owner")
        response = self.litter(mother=mock.Mock(id=db.Individual.select(db.fn.MAX(db.Individual.id)).scalar() + 1000))
        self.assertEqual((response.status_code, response.get_json()["detail"]), (404, "Kaninen finns inte."))

    def test_a_typed_count_in_my_herd_clears_preliminary(self):
        self.login("owner")
        first = self.litter().get_json()["id"]
        done = self.client.patch(f"/api/v2/breeding/{first}", json={"litter_size6w": 2})
        self.assertEqual(done.status_code, 200, done.get_data(as_text=True))
        self.assertEqual(done.get_json()["litter_size6w_preliminary"], False)
        self.assertFalse(db.Breeding.get_by_id(first).litter_size6w_preliminary)
