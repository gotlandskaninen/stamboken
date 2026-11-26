#!/usr/bin/env python3
"""
Tests for "nytt konto" in the status view (spec 5.1, 5.14): a main member's account made with a code to the matrikel's
e-mail is flagged for the round, and the genebank's manager or admin can undo exactly that link. Synthetic herds,
members and addresses only.

isort:skip_file
"""

from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
from utils.matrikel import link_member_user

from tests.test_member_changes import DetailsTest


class TestNewAccount(DetailsTest):
    def make_link(self):
        user = self.user("sjalv")
        link_member_user(self.member.id, user.id, actor=user, mode="matrikel_epost")
        linked = db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked")
        return user, linked.order_by(db.MatrikelAudit.id.desc()).get()

    def flag(self):
        view = arsrapport.status_view(self.round_, self.gotland.id)
        return next(row["flags"]["nytt_konto"] for row in view["rows"] if row["herd"] == "G9001")

    def undo(self, link_id, herd="G9001"):
        """Koppla bort, scoped to the herd and round of the status row (review round 1, 7)."""
        return self.api("POST", f"/besattning/{herd}/2025/kontokoppling/{link_id}/hav")

    def test_self_made_link_is_flagged_and_the_manager_undoes_it(self):  # 5.1
        self.assertIsNone(self.flag())
        user, audit = self.make_link()
        self.assertEqual(self.flag(), audit.id)
        self.login("man")
        response = self.undo(audit.id)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNone(db.Member.get_by_id(self.member.id).user_id)
        self.assertTrue(db.User.get_by_id(user.id).is_active)  # the account stays; only the link goes
        self.assertIsNone(self.flag())
        self.assertEqual(self.undo(audit.id).status_code, 404)  # the row offers it no more

    def test_an_old_link_cannot_undo_a_new_one(self):  # U13
        user, audit = self.make_link()
        self.login("man")
        self.undo(audit.id)
        link_member_user(self.member.id, user.id, actor=self.admin, mode="admin", confirmed_herd_ids=[self.h.id])
        self.assertEqual(self.undo(audit.id).status_code, 404)  # the row offers it no more
        self.assertEqual(db.Member.get_by_id(self.member.id).user_id, user.id)
        self.assertIsNone(self.flag())  # an admin's link is no "nytt konto"

    def test_only_the_herds_manager_or_admin(self):
        _, audit = self.make_link()
        mellerud_manager = self.user("mman", ("manager", self.mellerud.id))
        self.assertIsNotNone(mellerud_manager)
        self.login("mman")
        self.assertEqual(self.undo(audit.id).status_code, 403)
        self.login("owner")
        self.assertEqual(self.undo(audit.id).status_code, 403)
        self.assertIsNotNone(db.Member.get_by_id(self.member.id).user_id)

    def test_only_the_link_the_status_row_offers(self):  # review round 1, 7
        family = db.Member.create(
            first_name="Familj",
            last_name="Medlem",
            membership=self.membership(),
            role="familjemedlem",
            email="familj@example.invalid",
        )
        user = self.user("familj")
        link_member_user(family.id, user.id, actor=user, mode="matrikel_epost")
        audit = db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").get()
        self.login("man")
        self.assertEqual(self.undo(audit.id).status_code, 404)  # a family member's own account: never offered
        self.assertEqual(db.Member.get_by_id(family.id).user_id, user.id)
        _, main = self.make_link()
        self.assertEqual(self.undo(main.id, herd="G9002").status_code, 404)  # another herd's row
        db.Herd.update(is_active=False).where(db.Herd.id == self.h.id).execute()
        self.assertEqual(self.undo(main.id).status_code, 404)  # an inactive herd offers nothing
        self.assertIsNotNone(db.Member.get_by_id(self.member.id).user_id)

    def test_the_genebank_is_checked_again_on_the_locked_herd(self):  # review round 2
        _, audit = self.make_link()
        lock = arsrapport._lock_matrikel

        def moved_meanwhile(herd):  # an admin moves the herd to another genebank while Koppla bort waits
            db.Herd.update(genebank=self.mellerud).where(db.Herd.id == herd.id).execute()
            return lock(herd)

        self.login("man")  # Gotland's manager
        with mock.patch.object(arsrapport, "_lock_matrikel", moved_meanwhile):
            self.assertEqual(self.undo(audit.id).status_code, 403)
        self.assertIsNotNone(db.Member.get_by_id(self.member.id).user_id)
