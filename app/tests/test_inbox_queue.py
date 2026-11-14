"""The queue: who sees it, take / take over / assign, the state machine, documents, notices, "Mina inskick".

isort:skip_file
"""

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402

from tests.inbox_fixtures import InboxTest  # noqa: E402


class TestVisibility(InboxTest):
    def test_admin_manager_and_helpers_see_the_whole_queue(self):
        gotland, mellerud = self.item(0), self.item(2)
        for username in ("admin", "man", "hjalp", "mhjalp"):
            with self.subTest(username):
                self.login(username)
                resp = self.client.get("/api/v2/inkorg")
                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertEqual([i["id"] for i in resp.get_json()["items"]], [gotland.id, mellerud.id])
                self.assertEqual(self.client.get(f"/api/v2/inkorg/{mellerud.id}").status_code, 200)

    def test_an_owner_or_viewer_sees_none_of_it(self):
        item = self.item(0)
        self.assertEqual(self.client.get("/api/v2/inkorg").status_code, 401)
        for username in ("owner", "spec"):
            with self.subTest(username):
                self.login(username)
                self.assertEqual(self.client.get("/api/v2/inkorg").status_code, 403)
                self.assertEqual(self.client.get(f"/api/v2/inkorg/{item.id}").status_code, 403)
                self.assertEqual(self.post(f"/{item.id}/ta").status_code, 403)
                self.assertEqual(self.client.get("/api/v2/inkorg/notiser/antal").get_json()["works_in_queue"], False)

    def test_filters_and_counts(self):
        mine, untaken, mellerud = self.item(0), self.item(1), self.item(2)
        inbox.take(mine, self.helper, over=False)
        self.login("hjalp")

        def ids(query):
            resp = self.client.get(f"/api/v2/inkorg?{query}")
            self.assertEqual(resp.status_code, 200, resp.get_json())
            return [i["id"] for i in resp.get_json()["items"]]

        self.assertEqual(ids("mine=1"), [mine.id])
        self.assertEqual(ids("untaken=1"), [untaken.id, mellerud.id])
        self.assertEqual(ids(f"assigned_to={self.helper.id}"), [mine.id])
        self.assertEqual(ids(f"genebank_id={self.genebanks[1].id}"), [mellerud.id])
        self.assertEqual(ids("herd=G2"), [untaken.id])
        self.assertEqual(ids("state=tagen"), [mine.id])
        self.assertEqual(ids("kind=mail"), [])
        body = self.client.get("/api/v2/inkorg?state=tagen").get_json()
        self.assertEqual((body["counts"], body["total"]), ({"ny": 2, "tagen": 1}, 1))
        self.assertEqual(self.client.get("/api/v2/inkorg?state=okand").status_code, 400)

    def test_opening_an_item_is_logged_and_reads_its_notices(self):
        item = self.item(0)
        self.login("hjalp")
        self.assertEqual(
            self.client.get("/api/v2/inkorg/notiser/antal").get_json(), {"unread": 1, "works_in_queue": True}
        )
        detail = self.client.get(f"/api/v2/inkorg/{item.id}").get_json()
        self.assertEqual([e["kind"] for e in detail["events"]], ["inkommen", "oppnad"])
        self.assertEqual(detail["documents"][0]["proposal"], None)
        events = db.InboxEvent.select().where(db.InboxEvent.item == item.id).order_by(db.InboxEvent.id)
        self.assertEqual(
            [(e.kind, e.user_id) for e in events], [("inkommen", self.owner.id), ("oppnad", self.helper.id)]
        )
        self.assertEqual(self.client.get("/api/v2/inkorg/notiser/antal").get_json()["unread"], 0)


class TestTakeAndAssign(InboxTest):
    def test_take_and_take_over(self):
        item = self.item(0)
        self.login("hjalp")
        resp = self.post(f"/{item.id}/ta")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual((resp.get_json()["state"], resp.get_json()["assigned_to"]["id"]), ("tagen", self.helper.id))

        self.login("man")
        self.assertEqual(self.post(f"/{item.id}/ta").status_code, 409)
        resp = self.post(f"/{item.id}/ta-over")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self.reload(item).assigned_to_id, self.manager.id)
        notice = db.Notice.get(db.Notice.kind == "overtagen")
        self.assertEqual((notice.user_id, notice.item_id), (self.helper.id, item.id))
        kinds = [e.kind for e in db.InboxEvent.select().where(db.InboxEvent.item == item.id).order_by(db.InboxEvent.id)]
        self.assertEqual(kinds, ["inkommen", "tagen", "overtagen"])

    def test_a_closed_item_cannot_be_taken(self):
        item = self.item(0)
        inbox.take(item, self.helper, over=False)
        inbox.change_state(item, self.helper, "skrap")
        self.login("man")
        self.assertEqual(self.post(f"/{item.id}/ta").status_code, 409)
        self.assertEqual(self.post(f"/{item.id}/ta-over").status_code, 409)

    def test_assign_is_for_managers_and_admins_in_scope(self):
        gotland, mellerud = self.item(0), self.item(2)
        self.login("hjalp")
        self.assertEqual(self.post(f"/{gotland.id}/tilldela", user_id=self.helper.id).status_code, 403)
        self.login("man")  # manager of Gotland
        self.assertEqual(self.post(f"/{mellerud.id}/tilldela", user_id=self.mellerud_helper.id).status_code, 403)
        self.assertEqual(self.post(f"/{gotland.id}/tilldela", user_id=self.mellerud_helper.id).status_code, 400)
        self.assertEqual(self.post(f"/{gotland.id}/tilldela", user_id=self.owner.id).status_code, 400)
        resp = self.post(f"/{gotland.id}/tilldela", user_id=self.helper.id)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual((resp.get_json()["state"], resp.get_json()["assigned_to"]["id"]), ("tagen", self.helper.id))
        notice = db.Notice.get(db.Notice.kind == "tilldelad")
        self.assertEqual((notice.user_id, notice.item_id), (self.helper.id, gotland.id))
        self.login("admin")
        self.assertEqual(self.post(f"/{mellerud.id}/tilldela", user_id=self.mellerud_helper.id).status_code, 200)

    def test_assign_all_open_items_of_a_herd(self):
        first, second, closed, other = self.item(0), self.item(0), self.item(0), self.item(1)
        inbox.take(closed, self.helper, over=False)
        inbox.change_state(closed, self.helper, "skrap")
        self.login("man")
        resp = self.post("/tilldela", herd="G1", user_id=self.helper.id)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["assigned"], [first.id, second.id])
        self.assertIsNone(self.reload(other).assigned_to_id)
        self.assertEqual(self.reload(closed).state, "skrap")
        self.login("hjalp")
        self.assertEqual(self.post("/tilldela", herd="G2", user_id=self.helper.id).status_code, 403)

    def test_an_item_waiting_for_a_parent_keeps_waiting_when_assigned(self):
        item = self.item(0)
        inbox.take(item, self.helper, over=False)
        document = item.documents.get()
        inbox.update_document(item, document, self.helper, {"waiting_for": ["G1-2199"]})
        inbox.change_state(item, self.helper, "vantar_foralder")
        inbox.assign(item, self.manager, self.manager)
        self.assertEqual((item.state, item.assigned_to_id), ("vantar_foralder", self.manager.id))


class TestStates(InboxTest):
    STATES = inbox.OPEN_STATES + inbox.CLOSED_STATES

    def at(self, state):
        """An item in `state`, held by the helper when that state has a handler."""
        item = self.item(0)
        document = item.documents.get()
        document.waiting_for = ["G1-2199"]
        document.save()
        item.state = state
        item.assigned_to = self.helper if state in inbox.HELD_STATES or state in inbox.CLOSED_STATES else None
        item.save()
        return item

    def test_every_transition_follows_the_table(self):
        other = self.item(1)
        for start in self.STATES:
            for target in inbox.TRANSITIONS:
                with self.subTest(start=start, target=target):
                    item = self.at(start)
                    who = self.manager if start in inbox.CLOSED_STATES else self.helper
                    try:
                        inbox.change_state(item, who, target, note="Kullstorleken saknas", duplicate_of=other.id)
                        changed = True
                    except inbox.InboxError as exc:
                        self.assertEqual(exc.status, 409, exc.detail)
                        changed = False
                    self.assertEqual(changed, start in inbox.TRANSITIONS[target])
                    self.assertEqual(self.reload(item).state, target if changed else start)

    def test_only_the_handler_changes_the_state(self):
        item = self.at("tagen")
        self.login("man")
        self.assertEqual(self.post(f"/{item.id}/lage", state="skrap").status_code, 409)
        self.login("hjalp")
        self.assertEqual(self.post(f"/{item.id}/lage", state="skrap").status_code, 200)

    def test_the_rules_of_each_state(self):
        other = self.item(1)
        self.login("hjalp")
        item = self.at("tagen")
        db.InboxDocument.update(waiting_for=None).where(db.InboxDocument.item == item.id).execute()
        self.assertEqual(self.post(f"/{item.id}/lage", state="vantar_foralder").status_code, 400)
        self.assertEqual(self.post(f"/{item.id}/lage", state="ofullstandig").status_code, 400)
        self.assertEqual(self.post(f"/{item.id}/lage", state="dubblett").status_code, 400)
        self.assertEqual(self.post(f"/{item.id}/lage", state="dubblett", duplicate_of=item.id).status_code, 400)
        self.assertEqual(self.post(f"/{item.id}/lage", state="klar").status_code, 400)
        self.assertEqual(self.post(f"/{item.id}/lage", state="tagen").status_code, 409)

        resp = self.post(f"/{item.id}/lage", state="ofullstandig", note="Pappersintyget saknas")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        event = db.InboxEvent.select().where(db.InboxEvent.kind == "lage").get()
        self.assertEqual(event.detail, {"from": "tagen", "to": "ofullstandig", "note": "Pappersintyget saknas"})
        self.assertEqual(self.post(f"/{item.id}/lage", state="tagen").status_code, 200)

        resp = self.post(f"/{item.id}/lage", state="dubblett", duplicate_of=other.id)
        self.assertEqual(resp.get_json()["duplicate_of"], other.id)
        self.assertIsNotNone(self.reload(item).closed_at)

    def test_handing_over_to_the_manager(self):
        item = self.at("tagen")
        self.login("hjalp")
        resp = self.post(f"/{item.id}/lage", state="hos_genbanksansvarig", note="Datum före senaste rad")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIsNone(resp.get_json()["assigned_to"])
        notices = db.Notice.select().where(db.Notice.kind == "lamnad")
        self.assertEqual([n.user_id for n in notices], [self.manager.id])
        self.login("man")
        self.assertEqual(self.post(f"/{item.id}/ta").get_json()["state"], "tagen")

    def test_only_a_manager_or_admin_reopens(self):
        item = self.at("tagen")
        inbox.change_state(item, self.helper, "skrap")
        self.login("hjalp")
        self.assertEqual(self.post(f"/{item.id}/lage", state="tagen").status_code, 403)
        self.login("man")
        resp = self.post(f"/{item.id}/lage", state="tagen")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual((resp.get_json()["assigned_to"]["id"], resp.get_json()["closed_at"]), (self.manager.id, None))


class TestDocuments(InboxTest):
    def patch(self, item, document, **body):
        return self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json=body)

    def test_the_handler_describes_the_document(self):
        item = self.item(0)
        document = item.documents.get()
        self.login("hjalp")
        self.assertEqual(self.patch(item, document, rotation=90).status_code, 409)  # not taken
        self.post(f"/{item.id}/ta")
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        resp = self.patch(item, document, rotation=90, doc_type="intyg", cert_format="handskrivet", mask_rects=rects)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()["document"]
        self.assertEqual((body["rotation"], body["cert_format"], body["mask_rects"]), (90, "handskrivet", rects))
        self.assertEqual(
            self.patch(item, document, mask_rects=None).get_json()["document"]["mask_suggestion"],
            inbox.HANDWRITTEN_MASK,
        )
        for bad in [
            {"rotation": 45},
            {"doc_type": "kvitto"},
            {"cert_format": "okand"},
            {"mask_rects": [{"x": 0.5, "y": 0, "w": 0.6, "h": 1}]},
            {"mask_rects": [{"x": 0, "y": 0, "w": 0, "h": 1}]},
            {"waiting_for": ["inget nummer"]},
            {"waiting_for": ["G1-2111"]},  # already in Stamboken
            {"dismissed": "ja"},
            {"individual_id": 1},
            {},
        ]:
            with self.subTest(bad):
                self.assertEqual(self.patch(item, document, **bad).status_code, 400)
        self.assertEqual(
            self.patch(item, document, waiting_for=["G1-2199"]).get_json()["document"]["status"], "vantar_foralder"
        )
        other = self.item(1).documents.get()
        self.assertEqual(self.patch(item, other, rotation=0).status_code, 404)

    def test_dismissing_the_last_document_closes_the_item_and_tells_the_uploader(self):
        item = self.item(0, documents=2)
        first, second = item.documents.order_by(db.InboxDocument.id)
        self.login("hjalp")
        self.post(f"/{item.id}/ta")
        self.assertEqual(self.patch(item, first, dismissed=True).get_json()["item"]["state"], "tagen")
        self.assertEqual(self.patch(item, first, dismissed=False).get_json()["document"]["status"], "ny")
        self.patch(item, first, dismissed=True)
        resp = self.patch(item, second, dismissed=True)
        self.assertEqual(resp.get_json()["item"]["state"], "klar")
        self.assertEqual(resp.get_json()["document"]["status"], "avfardad")
        notice = db.Notice.get(db.Notice.kind == "klar")
        self.assertEqual(notice.user_id, self.owner.id)
        self.assertIsNotNone(notice.mailed_at)  # it has a mail of its own, never in the digest

    def test_the_same_image_twice_is_flagged(self):
        first, second = self.item(0), self.item(0)
        self.login("hjalp")
        (document,) = self.client.get(f"/api/v2/inkorg/{second.id}").get_json()["documents"]
        self.assertEqual(document["duplicates"], [{"item_id": first.id, "document_id": first.documents.get().id}])


class TestUploaderAndNotices(InboxTest):
    def test_my_uploads_in_plain_words(self):
        mine, other = self.item(0), self.item(1, sender=self.manager)
        inbox.take(mine, self.helper, over=False)
        self.login("owner")
        resp = self.client.get("/api/v2/inkorg/mina-inskick")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(
            resp.get_json()["items"],
            [
                {
                    "id": mine.id,
                    "status": "under_arbete",
                    "received_at": mine.received_at.isoformat(),
                    "herd": "G1",
                    "documents": 1,
                    "individuals": [],
                }
            ],
        )
        self.assertNotIn(other.id, [i["id"] for i in resp.get_json()["items"]])
        self.assertNotIn("assigned_to", resp.get_json()["items"][0])

    def test_notices_list_read_and_mail_setting(self):
        first, second = self.item(0), self.item(0)
        self.login("hjalp")
        body = self.client.get("/api/v2/inkorg/notiser").get_json()
        self.assertEqual(([n["item_id"] for n in body["notices"]], body["unread"]), ([second.id, first.id], 2))
        self.assertEqual(body["notices"][0]["text"], "Ny post i inläsningskön")
        resp = self.post("/notiser/las", ids=[body["notices"][0]["id"]])
        self.assertEqual(resp.get_json(), {"read": 1, "unread": 1})
        self.assertEqual(self.post("/notiser/las", all=True).get_json(), {"read": 1, "unread": 0})
        self.assertEqual(self.post("/notiser/las").status_code, 400)

        self.assertEqual(self.client.get("/api/v2/inkorg/notiser/installning").get_json(), {"mail_enabled": True})
        resp = self.client.put("/api/v2/inkorg/notiser/installning", json={"mail_enabled": False})
        self.assertEqual(resp.get_json(), {"mail_enabled": False})
        self.assertFalse(inbox.mail_enabled(self.helper))
        self.login("man")  # someone else's notices are not theirs to read
        self.assertEqual(self.post("/notiser/las", ids=[n["id"] for n in body["notices"]]).get_json()["read"], 0)
