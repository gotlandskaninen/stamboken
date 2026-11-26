#!/usr/bin/env python3
"""
Tests for the buyer outside the genebank kept from the report's sale dialog (Jonas 2026-11-26): the autosave carries
the typed buyer beside the draft, and the server keeps it as Dra tillbaka keeps one (K1, K2, FB6) until Skicka links
it. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
from datetime import date, datetime, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.buyer_contact as buyer_contact
import utils.database as db
import utils.herd_tracking as herd_tracking
import utils.inbox as inbox
from utils.herd_tracking import BUYER_REMOVED, CONTACT_OR_MEMBERSHIP_NEEDED

from tests.inbox_fixtures import QUALITY
from tests.test_arsrapport_kept_buyer import (
    BUYER,
    BUYER_TEXTS,
    EXTENDED,
    EXTENDED_UNTIL,
    KEPT_UNTIL,
    OTHER,
    PURGE_NIGHT,
    SOLD_ON,
    STOCKHOLM,
    KeptBuyerBase,
    contacts,
    sales,
)
from tests.test_buyer_notice_only import REAL_REPORT_BEVIS_FROM


class DialogBuyerTest(KeptBuyerBase):
    def sold(self, rabbit=None, ar=2025, manad=10, dag=10, till="utanfor"):
        """The draft as the client sends it (toDraft): `rabbit` sold, b Finns kvar, the buyer left out."""
        rabbit = rabbit or self.a
        sald = {"till": till, "ar": ar, "manad": manad, "dag": dag}
        entries = {str(rabbit.id): {"val": "sald", "sald": sald}, str(self.b.id): {"val": "kvar", "vikt": 2.8}}
        return {**arsrapport.stored_body(self.body()), "rabbits": entries, "form": {"rabbits": entries}}

    def save(self, data, kopare=None, updated_at=None, revision=None):
        response = self.api(
            "PUT",
            "/besattning/G9001/2025/utkast",
            data=data,
            updated_at=updated_at,
            submission_key=None,
            revision=revision,
            kopare=kopare,
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def kept(self, buyer=BUYER):
        """a sold outside the genebank on SOLD_ON, its buyer typed in the dialog and kept: (the answer, the buyer)."""
        answer = self.save(self.sold(), {str(self.a.id): buyer})
        return answer, db.BuyerContact.get_by_id(answer["kopare"][str(self.a.id)]["kopare_id"])

    def page(self):
        return self.api("GET", "/besattning/G9001/2025").get_json()

    def row(self, view=None):
        return next(row for row in (view or self.page())["rabbits"] if row["id"] == self.a.id)

    def sent(self, kopare_id=None, kopare=None, **body):
        """Skicka as the client sends it after a reload: the row's kept id, no buyer typed."""
        sald = {"kopare_id": kopare_id} if kopare_id is not None else {}
        sald |= {"kopare": kopare} if kopare is not None else {}
        entry = self.sald(self.a, "utanfor", 2025, 10, 10, kopare=kopare)
        entry[1]["sald"] |= sald
        return self.body(entry, self.kvar(self.b, vikt=2.8), **body)

    def buyer_mails(self):
        rows = db.MailMessage.select().where(db.MailMessage.recipient_kind == "buyer_contact")
        return [(m.kind, m.recipient_id) for m in rows.order_by(db.MailMessage.id)]

    def test_saving_the_dialog_keeps_the_buyer_and_the_draft_only_its_claim(self):
        answer, contact = self.kept()
        key = str(self.a.id)
        self.assertEqual(answer["kopare"], {key: {"kopare_id": contact.id, "kept_buyer_date": SOLD_ON.isoformat()}})
        self.assertEqual(answer["refusals"], [])
        self.assertEqual((contact.name, contact.email, contact.purge_at), (BUYER["name"], BUYER["email"], KEPT_UNTIL))
        claim = {"kopare_id": contact.id, "fran_rapport": None, "kopare_datum": {"ar": 2025, "manad": 10, "dag": 10}}
        for body in (self.draft(), self.draft()["form"]):
            self.assertEqual(
                body["rabbits"][key]["sald"], {"till": "utanfor", "ar": 2025, "manad": 10, "dag": 10, **claim}
            )
        view = self.page()
        self.assertEqual(self.row(view)["kept_buyer_date"], SOLD_ON.isoformat())
        for text in (json.dumps(self.draft()), json.dumps(view), json.dumps(answer)):
            self.assertFalse([value for value in BUYER_TEXTS if value in text], text[:200])
        self.assertEqual(self.buyer_mails(), [])  # the buyer is told once the sale is registered

    def test_skicka_registers_the_kept_buyer_and_queues_its_mail(self):
        _, contact = self.kept()
        self.assertEqual(self.refused(self.sent()), [(self.a.id, "kopare_saknas")])  # the body names no buyer
        self.ok(self.sent(contact.id))
        (sale,) = sales(self.a, active=True)
        self.assertEqual(sale.holder_contact_id, contact.id)
        self.assertEqual(contacts(), {contact.id: db.BuyerContact.purge_at_for(SOLD_ON)})
        self.assertEqual(self.buyer_mails(), [("kopare.information", contact.id)])
        self.assertFalse(db.YearlyReportDraft.select().exists())

    def test_skicka_before_the_autosave_answers_takes_the_kept_buyer(self):
        _, contact = self.kept()
        self.ok(self.sent(contact.id, kopare=BUYER))  # Skicka cancelled the autosave that would drop the values
        self.assertEqual([sale.holder_contact_id for sale in sales(self.a, active=True)], [contact.id])
        self.assertEqual(self.buyer_mails(), [("kopare.information", contact.id)])

    def test_a_new_buyer_replaces_the_kept_one_in_the_same_save(self):
        answer, contact = self.kept()
        replaced = self.save(self.sold(), {str(self.a.id): OTHER}, updated_at=answer["updated_at"])
        new = replaced["kopare"][str(self.a.id)]["kopare_id"]
        self.assertEqual(contacts(), {new: KEPT_UNTIL})
        self.assertNotEqual(new, contact.id)
        self.assertEqual(self.draft()["rabbits"][str(self.a.id)]["sald"]["kopare_id"], new)

    def test_another_choice_a_herd_in_the_genebank_or_a_new_date_drops_it(self):
        moved = self.sold(manad=9)
        for case, data in {
            "Finns kvar": {**self.sold(), "rabbits": {str(self.a.id): {"val": "kvar", "vikt": 2.8}}},
            "a herd in the genebank": self.sold(till="G9002"),
            "another month": moved,
        }.items():
            with self.subTest(case):
                db.YearlyReportDraft.delete().execute()
                answer, _ = self.kept()
                data = {**data, "form": {"rabbits": data["rabbits"]}}
                self.save(data, updated_at=answer["updated_at"])
                self.assertEqual(contacts(), {})
                self.assertNotIn("kopare_id", json.dumps(self.draft()))

    def test_the_client_keeps_the_claim_it_was_given(self):  # the client sends kopare_id back; the server's stays
        answer, contact = self.kept()
        data = self.sold()
        data["rabbits"][str(self.a.id)]["sald"]["kopare_id"] = contact.id + 1
        self.save(data, updated_at=answer["updated_at"])
        self.assertEqual(self.draft()["rabbits"][str(self.a.id)]["sald"]["kopare_id"], contact.id)
        self.assertEqual(list(contacts()), [contact.id])

    def test_sald_utanfor_genbanken_keeps_no_buyer(self):  # #273
        answer = self.save(self.sold(), {str(self.a.id): {"not_recorded": True}})
        self.assertEqual((answer["kopare"], answer["refusals"], contacts()), ({}, [], {}))
        self.assertNotIn("kopare_id", json.dumps(self.draft()))

    def test_sald_utanfor_genbanken_stays_in_the_draft_and_skicka_takes_it_as_before(self):  # #273
        key, data = str(self.a.id), self.sold()
        data["rabbits"][key]["sald"]["kopare"] = {"not_recorded": True}  # the body and the form copy alike
        self.save(data)
        for body in (self.draft(), self.draft()["form"], self.page()["draft"]["data"]["form"]):
            self.assertEqual(body["rabbits"][key]["sald"]["kopare"], {"not_recorded": True})
        self.ok(self.sent(kopare={"not_recorded": True}))  # the sale as a reloaded page sends it
        (sale,) = sales(self.a, active=True)
        self.assertEqual((sale.herd.herd, sale.holder_contact_id, sale.buyer_removed), ("GX1", None, False))
        self.assertEqual(contacts(), {})

    def test_a_draft_takes_only_the_bare_marker(self):  # anything more may name the buyer
        key = str(self.a.id)
        for kopare in ({"not_recorded": True, "name": "Zelda Keptbuyer"}, {"not_recorded": 1}, {**OTHER}):
            for where in ("body", "form"):
                with self.subTest(kopare=kopare, where=where):
                    data = json.loads(json.dumps(self.sold()))
                    (data if where == "body" else data["form"])["rabbits"][key]["sald"]["kopare"] = kopare
                    response = self.api("PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None)
                    self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertFalse(db.YearlyReportDraft.select().exists())

    def test_choosing_sald_utanfor_genbanken_drops_the_kept_buyer(self):  # #273: not even a kept one
        answer, contact = self.kept()
        data = self.sold()
        data["rabbits"][str(self.a.id)]["sald"] |= {"kopare": {"not_recorded": True}, "kopare_id": contact.id}
        self.save(data, updated_at=answer["updated_at"])
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))

    def test_a_buyer_anywhere_in_the_draft_is_refused(self):  # review r1: a buyer misplaced inside `data`
        key = str(self.a.id)
        for data in ({**self.sold(), "kopare": {key: BUYER}}, {**self.sold(), "extra": [{"kopare": BUYER}]}):
            with self.subTest(data=list(data)[-1]):
                response = self.api("PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None)
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertFalse(db.YearlyReportDraft.select().exists())

    def test_a_typed_buyer_against_the_forms_marker_keeps_nothing(self):  # review r1: no contact without a claim
        key, data = str(self.a.id), self.sold()
        data["rabbits"][key]["sald"]["kopare"] = {"not_recorded": True}
        answer = self.save(data, {key: BUYER})
        self.assertEqual((answer["kopare"], contacts()), ({}, {}))

    def test_a_key_no_rabbit_has_is_no_server_error(self):  # review r1: filtered before any query
        answer = self.save(self.sold(), {"9" * 30: BUYER})
        self.assertEqual((answer["kopare"], contacts()), ({}, {}))

    def test_a_refused_new_buyer_lets_go_of_the_kept_one(self):  # review r1: B refused must not leave A for Skicka
        answer, contact = self.kept()
        email_only = {**OTHER, "email": "xena@example.invalid"}  # no tick: refused
        answer = self.save(self.sold(), {str(self.a.id): email_only}, updated_at=answer["updated_at"])
        self.assertEqual([r["code"] for r in answer["refusals"]], ["kopare"])
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))
        self.assertNotIn("kept_buyer_date", self.row())
        self.assertEqual(self.refused(self.sent(contact.id)), [(self.a.id, "kopare_saknas")])

    def test_a_buyer_erased_before_skicka_is_never_registered_for_that_sale(self):  # review r1
        answer, contact = self.kept()
        buyer_contact.erase_buyer_contact(contact.id, db.User.get_by_id(self.admin.id))
        self.assertIn(SOLD_ON.isoformat(), self.row()["removed_buyer_dates"])
        again = self.save(self.sold(), {str(self.a.id): BUYER}, updated_at=answer["updated_at"])
        self.assertEqual(again["refusals"], [{"individual_id": self.a.id, "code": "kopare", "message": BUYER_REMOVED}])
        self.assertEqual(contacts(), {})
        self.assertEqual(self.refused(self.sent(kopare=BUYER)), [(self.a.id, "kopare")])
        self.ok(self.sent(contact.id))  # without a buyer: a sale whose buyer was removed
        (sale,) = sales(self.a, active=True)
        self.assertEqual((sale.holder_contact_id, sale.buyer_removed), (None, True))
        self.assertEqual(contacts(), {})

    def test_an_invalid_buyer_is_refused_beside_a_saved_draft(self):
        email_only = {**OTHER, "email": "xena@example.invalid"}
        answer = self.save(self.sold(), {str(self.a.id): email_only})
        self.assertEqual(
            answer["refusals"],
            [{"individual_id": self.a.id, "code": "kopare", "message": CONTACT_OR_MEMBERSHIP_NEEDED}],
        )
        self.assertEqual((answer["kopare"], contacts()), ({}, {}))
        self.assertTrue(db.YearlyReportDraft.select().exists())

    def test_the_year_rules_are_the_sales(self):  # #273: the report takes the bevis from 2027
        with mock.patch.object(herd_tracking, "REPORT_BEVIS_FROM", REAL_REPORT_BEVIS_FROM):
            answer = self.save(self.sold(), {str(self.a.id): BUYER})
            self.assertEqual(
                answer["refusals"],
                [{"individual_id": self.a.id, "code": "kopare", "message": herd_tracking.REPORT_BEVIS_NOT_YET}],
            )
            notice = {**OTHER, "email": "xena@example.invalid", "notice_only": True}
            answer = self.save(self.sold(), {str(self.a.id): notice}, updated_at=answer["updated_at"])
        contact = db.BuyerContact.get_by_id(answer["kopare"][str(self.a.id)]["kopare_id"])
        self.assertTrue(contact.email_notice_only)

    def test_the_owner_needs_the_address_and_a_manager_does_not(self):
        no_address = {k: v for k, v in OTHER.items() if k != "postal_address"}
        answer = self.save(self.sold(), {str(self.a.id): no_address})
        self.assertEqual([r["message"] for r in answer["refusals"]], ["Ange köparens postadress."])
        self.login("man")
        answer = self.save(self.sold(), {str(self.a.id): no_address}, updated_at=answer["updated_at"])
        self.assertEqual(answer["refusals"], [])
        self.assertEqual([c.postal_address for c in db.BuyerContact.select()], [None])

    def test_a_caretaker_keeps_no_buyer(self):  # F1: a caretaker's sale is a proposal, whose buyer stays in memory
        self.caretaker()
        self.login("skotare")
        answer = self.save(self.sold(), {str(self.a.id): BUYER})
        self.assertEqual((answer["kopare"], answer["refusals"], contacts()), ({}, [], {}))

    def test_a_sale_the_report_holds_is_corrected_at_skicka(self):  # Ändra: the old way, no kept buyer
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        before = contacts()
        answer = self.save(self.sold(), {str(self.a.id): OTHER}, revision=1)
        self.assertEqual((answer["kopare"], contacts()), ({}, before))

    def test_a_new_sale_in_andra_keeps_its_buyer_and_skicka_links_it(self):
        self.ok(self.body(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8)))
        answer = self.save(self.sold(), {str(self.a.id): BUYER}, revision=1)
        contact_id = answer["kopare"][str(self.a.id)]["kopare_id"]
        self.ok(self.sent(contact_id, revision=1))
        self.assertEqual([sale.holder_contact_id for sale in sales(self.a, active=True)], [contact_id])

    def test_an_erased_buyers_sale_keeps_no_new_buyer(self):
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        buyer_contact.erase_buyer_contact(sales(self.a)[0].holder_contact_id, self.admin)
        self.withdrawn(1)
        answer = self.save(self.sold(), {str(self.a.id): OTHER}, updated_at=self.page()["draft"]["updated_at"])
        self.assertEqual(answer["refusals"], [{"individual_id": self.a.id, "code": "kopare", "message": BUYER_REMOVED}])
        self.assertEqual(contacts(), {})

    def test_never_sent_it_goes_at_kept_until(self):
        _, contact = self.kept()
        buyer_contact.run(datetime(2026, 3, 31, 3, 50, tzinfo=STOCKHOLM))  # the night after end_date
        self.assertEqual(list(contacts()), [contact.id])
        self.at(PURGE_NIGHT)
        self.assertEqual(buyer_contact.purge_expired(arsrapport.now()), 1)
        deleted = db.AuditLog.get(
            db.AuditLog.table_name == "buyer_contact",
            db.AuditLog.operation == "DELETE",
            db.AuditLog.record_id == str(contact.id),
        )
        self.assertEqual(deleted.new_data, {"action": "gallring_kvar"})
        # The claim stays in the draft, but names nothing: the row needs a buyer again, and Skicka says so.
        self.assertNotIn("kept_buyer_date", self.row())
        self.login("man")  # after end_date only an editor sends
        refusals = self.refused(self.sent(contact.id, reason="Kom in sent"))
        self.assertEqual(refusals, [(self.a.id, "kopare_saknas")])

    def test_an_extended_round_moves_it(self):  # K2
        _, contact = self.kept()
        arsrapport.save_round(2025, self.admin, end_date=EXTENDED)
        self.assertEqual(contacts(), {contact.id: EXTENDED_UNTIL})

    def test_dra_tillbaka_keeps_an_open_drafts_buyer(self):
        self.ok(self.body(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8)))
        answer = self.save(self.sold(), {str(self.a.id): BUYER}, revision=1)
        contact_id = answer["kopare"][str(self.a.id)]["kopare_id"]
        self.withdrawn(1)
        self.assertEqual(self.draft()["rabbits"][str(self.a.id)]["sald"]["kopare_id"], contact_id)
        self.assertEqual(list(contacts()), [contact_id])
        self.ok(self.sent(contact_id))
        self.assertEqual([sale.holder_contact_id for sale in sales(self.a, active=True)], [contact_id])

    def test_skicka_without_the_sale_drops_it(self):  # FB6: the draft goes
        self.kept()
        self.ok(self.body(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8)))
        self.assertEqual(contacts(), {})

    def test_skicka_with_another_typed_buyer_drops_it(self):  # "eller skriv en ny köpare"
        _, contact = self.kept()
        self.ok(self.sent(kopare=OTHER))
        (sale,) = sales(self.a, active=True)
        self.assertEqual(list(contacts()), [sale.holder_contact_id])
        self.assertNotEqual(sale.holder_contact_id, contact.id)
        self.assertEqual(sale.holder_contact.name, OTHER["name"])

    def test_dra_tillbaka_drops_a_kept_buyer_whose_rabbit_it_no_longer_takes(self):  # FB1, FB6
        self.ok(self.body(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8)))
        answer = self.save(self.sold(), {str(self.a.id): BUYER}, revision=1)
        contact_id = answer["kopare"][str(self.a.id)]["kopare_id"]
        # As if a's row had left the list meanwhile: the server's draft names a rabbit Skicka does not take.
        (x,) = self.rabbits(self.g9002, 1)
        data = self.draft()
        for body in (data, data["form"]):
            body["rabbits"][str(x.id)] = body["rabbits"].pop(str(self.a.id))
        db.YearlyReportDraft.update(data=data).execute()
        self.assertEqual(contacts(), {contact_id: KEPT_UNTIL})
        self.withdrawn(1)
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))

    def test_a_rabbit_skicka_does_not_take_keeps_no_buyer(self):
        (x,) = self.rabbits(self.g9002, 1)  # another herd's rabbit
        answer = self.save(self.sold(x), {str(x.id): BUYER})
        self.assertEqual((answer["kopare"], contacts()), ({}, {}))

    def notice_kept(self):
        """A buyer without a försäljningsbevis kept on DAY0, as the purge reads the day it came (created_at)."""
        _, contact = self.kept({**OTHER, "email": "xena@example.invalid", "notice_only": True})
        db.BuyerContact.update(created_at=arsrapport.now()).execute()
        return contact

    def test_a_buyer_without_bevis_is_told_at_skicka(self):  # #273: kopare.information when the sale is registered
        contact = self.notice_kept()
        self.ok(self.sent(contact.id))
        self.assertEqual(self.buyer_mails(), [("kopare.information", contact.id)])
        self.assertEqual(buyer_contact.purge_uninformed(arsrapport.now() + timedelta(days=29)), 0)

    def test_a_buyer_without_bevis_never_sent_goes_after_a_month(self):  # #273, art. 14.3: not at kept_until
        contact = self.notice_kept()
        self.assertEqual(buyer_contact.purge_uninformed(arsrapport.now() + timedelta(days=29)), 0)
        self.assertEqual(buyer_contact.purge_uninformed(arsrapport.now() + timedelta(days=31)), 1)
        self.assertEqual(contacts(), {})
        deleted = db.AuditLog.get(
            db.AuditLog.table_name == "buyer_contact",
            db.AuditLog.operation == "DELETE",
            db.AuditLog.record_id == str(contact.id),
        )
        self.assertEqual(deleted.new_data, {"action": "ej_informerad"})
        self.assertNotIn("kept_buyer_date", self.row())  # the row needs the buyer again

    def test_dra_tillbaka_may_not_name_the_drafts_buyer(self):  # review r1: void_reason lives in audit_log
        self.ok(self.body(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8)))
        self.save(self.sold(), {str(self.a.id): BUYER}, revision=1)
        self.login("man")
        response = self.api("POST", "/besattning/G9001/2025/dra-tillbaka", revision=1, reason="Zelda vill inte")
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual([r["code"] for r in response.get_json()["refusals"]], ["orsak_kopare"])

    def test_a_rejected_proposal_takes_the_drafts_buyer_for_that_rabbit(self):  # review r1: no orphan
        self.caretaker()
        self.login("skotare")
        self.ok(self.body(self.sald(self.a, "G9002", 2025, 10, 10), self.kvar(self.b, vikt=2.8)))
        (proposal,) = db.SaleProposal.select()
        self.login("owner")
        self.save(self.sold(), {str(self.a.id): BUYER}, revision=1)
        self.assertEqual(len(contacts()), 1)
        self.login("man")
        response = self.api("POST", f"/forslag/{proposal.id}/avvisa", reason="Fel besättning", then="kvar")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))

    def test_after_the_last_day_nothing_is_kept_as_the_dialog_says(self):  # review r1: one rule for both
        self.at(date(2026, 3, 31))  # the day after end_date: only an editor or a helper still enters
        self.login("man")
        answer = self.save(self.sold(), {str(self.a.id): BUYER})
        self.assertEqual((answer["kopare"], contacts()), ({}, {}))

    def test_a_paper_autosave_after_the_item_left_the_helper_writes_nothing(self):  # review r1
        item, _ = inbox.create_upload(self.owner, self.h, None, [("inkorg/original/x.jpg", "0" * 64, QUALITY)])
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == item.id).execute()
        helper = db.User.get_by_id(self.helper.id)
        inbox.take(db.InboxItem.get_by_id(item.id), helper, over=False)
        access = arsrapport.report_access(helper, self.h, item.id)
        self.assertEqual((access.role, access.source), ("helper", "paper"))
        inbox.take(db.InboxItem.get_by_id(item.id), db.User.get_by_id(self.manager.id), over=True)  # meanwhile
        with self.assertRaises(arsrapport.ArsrapportError) as caught:
            arsrapport.save_draft(
                self.h, self.round_, access, helper, self.sold(), None, None, None, {str(self.a.id): BUYER}
            )
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(contacts(), {})
        self.assertFalse(db.YearlyReportDraft.select().exists())

    def test_a_reason_may_not_name_the_kept_buyer(self):  # it lives in audit_log; no row holds the buyer yet
        self.login("man")
        _, contact = self.kept()
        refusals = self.refused(self.sent(contact.id, reason="Zelda hämtade den i oktober"))
        self.assertIn((None, "orsak_kopare"), refusals)
