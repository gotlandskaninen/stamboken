#!/usr/bin/env python3
"""
Tests for "nytt konto" in the status view (spec 5.1, 5.14): a main member's account made with a code to the matrikel's
e-mail is flagged for the round, and the genebank's manager or admin can undo exactly that link. Synthetic herds,
members and addresses only.

isort:skip_file
"""

import utils.arsrapport as arsrapport
import utils.database as db
from utils.matrikel import link_member_user

from tests.test_member_changes import DetailsTest


class TestNewAccount(DetailsTest):
    def make_link(self):
        user = self.user("sjalv")
        link_member_user(self.member.id, user.id, actor=user, mode="matrikel_epost")
        return user, db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").get()

    def flag(self):
        view = arsrapport.status_view(self.round_, self.gotland.id)
        return next(row["flags"]["nytt_konto"] for row in view["rows"] if row["herd"] == "G9001")

    def test_self_made_link_is_flagged_and_the_manager_undoes_it(self):  # 5.1
        self.assertIsNone(self.flag())
        user, audit = self.make_link()
        self.assertEqual(self.flag(), audit.id)
        self.login("man")
        response = self.api("POST", f"/kontokoppling/{audit.id}/hav")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNone(db.Member.get_by_id(self.member.id).user_id)
        self.assertTrue(db.User.get_by_id(user.id).is_active)  # the account stays; only the link goes
        self.assertIsNone(self.flag())
        self.assertEqual(self.api("POST", f"/kontokoppling/{audit.id}/hav").status_code, 409)

    def test_an_old_link_cannot_undo_a_new_one(self):  # U13
        user, audit = self.make_link()
        self.login("man")
        self.api("POST", f"/kontokoppling/{audit.id}/hav")
        link_member_user(self.member.id, user.id, actor=self.admin, mode="admin", confirmed_herd_ids=[self.h.id])
        self.assertEqual(self.api("POST", f"/kontokoppling/{audit.id}/hav").status_code, 409)
        self.assertEqual(db.Member.get_by_id(self.member.id).user_id, user.id)
        self.assertIsNone(self.flag())  # an admin's link is no "nytt konto"

    def test_only_the_herds_manager_or_admin(self):
        _, audit = self.make_link()
        mellerud_manager = self.user("mman", ("manager", self.mellerud.id))
        self.assertIsNotNone(mellerud_manager)
        self.login("mman")
        self.assertEqual(self.api("POST", f"/kontokoppling/{audit.id}/hav").status_code, 403)
        self.login("owner")
        self.assertEqual(self.api("POST", f"/kontokoppling/{audit.id}/hav").status_code, 403)
        self.assertIsNotNone(db.Member.get_by_id(self.member.id).user_id)
