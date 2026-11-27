"""The queue: who sees it, take / take over / assign, the state machine, documents, notices, "Mina inskick".

isort:skip_file
"""

from datetime import timedelta  # noqa: E402

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.mail as mail  # noqa: E402

from tests.inbox_fixtures import InboxTest  # noqa: E402


class TestVisibility(InboxTest):
    def test_mail_mentions_are_suggestions_filtered_for_each_reader(self):
        db.Individual.update(voided=True).where(db.Individual.number == "G1-1911").execute()
        # G1-2112's current holder is in Gotland even if its recorded origin is elsewhere.
        db.Individual.update(origin_herd=self.herds[2]).where(db.Individual.number == "G1-2112").execute()
        item = db.InboxItem.create(kind="meddelande", message="(g1-2111), M3-2111 och G9-9999.")
        inbox.log_event(item, None, "inkommen", subject="Fråga om G1-2112 och G1-2111")
        inbox.log_event(item, None, "svar", subject="M3-1811", text="G2-1711, G1-1911. Feltryck G2-2011x.")
        for username, expected in (
            ("hjalp", ["G1-2111", "G1-2112", "G2-1711"]),
            ("mhjalp", ["M3-1811", "M3-2111"]),
        ):
            with self.subTest(username):
                self.login(username)
                resp = self.client.get(f"/api/v2/inkorg/{item.id}")
                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertEqual(resp.get_json()["mentioned_individuals"], expected)
                self.assertEqual(resp.get_json()["documents"], [])
        self.assertFalse(db.InboxOperation.select().exists())

    def test_admin_manager_and_helpers_see_the_whole_queue(self):
        gotland, mellerud = self.item(0), self.item(2)
        for username in ("admin", "man", "hjalp", "mhjalp"):
            with self.subTest(username):
                self.login(username)
                resp = self.client.get("/api/v2/inkorg?scope=alla")
                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertEqual([i["id"] for i in resp.get_json()["items"]], [gotland.id, mellerud.id])
                self.assertEqual(self.client.get(f"/api/v2/inkorg/{mellerud.id}").status_code, 200)

    def test_the_scope_is_ones_own_genebanks_and_the_unknown_by_default_for_managers_and_helpers(self):
        gotland, mellerud = self.item(0), self.item(2)
        unknown = db.InboxItem.create(kind="meddelande", sender_address="okand@example.org")
        inbox.take(gotland, self.helper, over=False)
        gotland_id, mellerud_id = self.genebanks[0].id, self.genebanks[1].id
        expected = {
            # username: (default scope, item ids by default, my_genebanks)
            "admin": ("alla", [gotland.id, mellerud.id, unknown.id], []),
            "man": ("mina", [gotland.id, unknown.id], [gotland_id]),
            "hjalp": ("mina", [gotland.id, unknown.id], [gotland_id]),
            "mhjalp": ("mina", [mellerud.id, unknown.id], [mellerud_id]),
        }
        for username, (scope, ids, genebanks) in expected.items():
            with self.subTest(username):
                self.login(username)
                body = self.client.get("/api/v2/inkorg").get_json()
                self.assertEqual((body["scope"], body["my_genebanks"]), (scope, genebanks))
                self.assertEqual([i["id"] for i in body["items"]], ids)
                self.assertEqual(sum(body["counts"].values()), len(ids))  # the counts follow the scope
                every = self.client.get("/api/v2/inkorg?scope=alla").get_json()
                self.assertEqual([i["id"] for i in every["items"]], [gotland.id, mellerud.id, unknown.id])
                self.assertEqual((every["scope"], every["counts"]), ("alla", {"ny": 2, "tagen": 1}))
                # a filter never hides my_genebanks: the item page reads it with limit=1
                one = self.client.get("/api/v2/inkorg?limit=1&state=klar").get_json()
                self.assertEqual((one["items"], one["my_genebanks"]), ([], genebanks))
        self.login("admin")
        admin_mine = self.client.get("/api/v2/inkorg?scope=mina").get_json()["items"]
        self.assertEqual([i["id"] for i in admin_mine], [unknown.id])  # no genebank of its own: the unknown only
        self.assertEqual(self.client.get("/api/v2/inkorg?scope=min").status_code, 400)
        self.login("mhjalp")  # reads the other genebank's item, but cannot work it
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{gotland.id}").status_code, 200)
        document = gotland.documents.get()
        for path in ("ta", "ta-over"):
            self.assertEqual(self.post(f"/{gotland.id}/{path}").status_code, 403)
        saved = self.post(f"/{gotland.id}/dokument/{document.id}/spara", action="ny_kanin")
        self.assertEqual(saved.status_code, 403)
        self.assertEqual(self.reload(gotland).assigned_to_id, self.helper.id)  # nothing taken over
        self.assertFalse(db.InboxOperation.select().exists())

    def test_the_queue_is_worked_only_in_ones_own_genebanks_and_the_unknown(self):
        for username, (gotland, mellerud, unknown) in {
            "hjalp": (True, False, True),
            "mhjalp": (False, True, True),
            "admin": (True, True, True),
        }.items():
            self.login(username)
            for herd, allowed in ((0, gotland), (2, mellerud), (None, unknown)):
                with self.subTest(username, herd=herd):
                    item = self.item(herd) if herd is not None else db.InboxItem.create(kind="meddelande")
                    self.assertEqual(self.post(f"/{item.id}/ta-over").status_code, 200 if allowed else 403)
                    self.assertEqual(self.post(f"/{item.id}/ta").status_code, 200 if allowed else 403)
                    self.assertEqual(self.reload(item).assigned_to_id is not None, allowed)
                    if not allowed:
                        patch = self.client.patch(
                            f"/api/v2/inkorg/{item.id}/dokument/{item.documents.get().id}", json={"dismissed": True}
                        )
                        self.assertEqual(patch.status_code, 403)

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

    def test_the_handlers_are_listed_by_name_for_the_queue_only(self):
        inactive = self.user("gammal", ("helper", self.genebanks[0].id))
        db.User.update(is_active=False).where(db.User.id == inactive.id).execute()
        self.assertEqual(self.client.get("/api/v2/inkorg/handlaggare").status_code, 401)
        self.login("owner")
        self.assertEqual(self.client.get("/api/v2/inkorg/handlaggare").status_code, 403)
        self.login("man")
        resp = self.client.get("/api/v2/inkorg/handlaggare")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        people = resp.get_json()["people"]
        ids = {p["id"] for p in people}
        self.assertTrue({self.helper.id, self.mellerud_helper.id, self.manager.id, self.admin.id} <= ids)
        self.assertNotIn(inactive.id, ids)
        self.assertNotIn(self.owner.id, ids)
        for person in people:
            self.assertEqual(set(person), {"id", "name"})

    def test_a_blurry_document_flags_the_item_in_the_list(self):
        sharp, blurred = self.item(0), self.item(1, documents=2)
        db.InboxDocument.update(quality={"short_side": 1200, "sharpness": 3.0, "brightness": 200.0}).where(
            db.InboxDocument.item == blurred.id
        ).execute()
        self.login("hjalp")
        flags = {i["id"]: i["maybe_blurry"] for i in self.client.get("/api/v2/inkorg").get_json()["items"]}
        self.assertEqual(flags, {sharp.id: False, blurred.id: True})

    def test_filters_and_counts(self):
        mine, untaken, mellerud = self.item(0), self.item(1), self.item(2)
        inbox.take(mine, self.helper, over=False)
        self.login("hjalp")

        def ids(query):
            resp = self.client.get(f"/api/v2/inkorg?scope=alla&{query}")
            self.assertEqual(resp.status_code, 200, resp.get_json())
            return [i["id"] for i in resp.get_json()["items"]]

        self.assertEqual(ids("mine=1"), [mine.id])
        self.assertEqual(ids("untaken=1"), [untaken.id, mellerud.id])
        self.assertEqual(ids(f"assigned_to={self.helper.id}"), [mine.id])
        self.assertEqual(ids(f"genebank_id={self.genebanks[1].id}"), [mellerud.id])
        self.assertEqual(ids("herd=G2"), [untaken.id])
        self.assertEqual(ids("state=tagen"), [mine.id])
        self.assertEqual(ids("kind=mail"), [])
        body = self.client.get("/api/v2/inkorg?scope=alla&state=tagen").get_json()
        self.assertEqual((body["counts"], body["total"]), ({"ny": 2, "tagen": 1}, 1))
        self.assertEqual(self.client.get("/api/v2/inkorg?state=okand").status_code, 400)

    def test_mail_summary_uses_original_subject_and_includes_skipped_replies_until_purged(self):
        item = db.InboxItem.create(kind="meddelande", sender_address="inkorg@example.org")
        start = inbox.log_event(item, None, "inkommen", subject="Intyg")
        reply = inbox.log_event(item, None, "svar", subject="Nytt ämne", not_saved=["bilaga.txt"])
        self.login("hjalp")

        def summary():
            row = self.client.get("/api/v2/inkorg").get_json()["items"][0]
            self.assertNotIn("sender_address", row)
            return row["subject"], row["has_skipped"], row["member_name"]

        self.assertEqual(summary(), ("Intyg", True, None))
        db.InboxEvent.update(detail={}).where(db.InboxEvent.id.in_([start.id, reply.id])).execute()
        member = db.Member.create(
            first_name="Medlem", last_name="A", membership=db.Membership.create(member_number=9001)
        )
        db.InboxItem.update(member=member).where(db.InboxItem.id == item.id).execute()
        self.assertEqual(summary(), (None, False, "Medlem A"))
        detail = self.client.get(f"/api/v2/inkorg/{item.id}").get_json()
        self.assertEqual(detail["sender_address"], "inkorg@example.org")

    def test_modes_follow_scope_while_prefix_sort_and_pagination_only_change_the_list(self):
        mine, unassigned, done, other, unknown = self.item(0), self.item(1), self.item(0), self.item(2), self.item(0)
        db.InboxItem.update(assigned_to=self.helper, state="vantar_uppfodare").where(db.InboxItem.id == mine).execute()
        db.InboxItem.update(assigned_to=self.helper, state="skrap").where(db.InboxItem.id == done).execute()
        db.InboxItem.update(herd=None, genebank=None, state="hos_genbanksansvarig").where(
            db.InboxItem.id == unknown
        ).execute()
        self.login("hjalp")

        def items(query, expected, counts):
            resp = self.client.get(f"/api/v2/inkorg?{query}")
            self.assertEqual(resp.status_code, 200, resp.get_json())
            body = resp.get_json()
            self.assertEqual([row["id"] for row in body["items"]], expected)
            self.assertEqual(body["mode_counts"], counts)
            self.assertEqual(body["next_untaken"], [unassigned.id, other.id if "scope=alla" in query else unknown.id])

        scoped = {"nya": 2, "mina": 1, "oppna": 3, "klara": 1}
        items("mode=mina", [mine.id], scoped)
        items("mode=nya", [unassigned.id, unknown.id], scoped)
        items("mode=klara", [done.id], scoped)
        items("mode=oppna&herd_prefix=g&order=newest&limit=1", [unassigned.id], scoped)
        items("mode=nya&scope=alla", [unassigned.id, other.id, unknown.id], {**scoped, "nya": 3, "oppna": 4})
        for query in ("mode=okand", "order=okand"):
            self.assertEqual(self.client.get(f"/api/v2/inkorg?{query}").status_code, 400)

    def test_next_untaken_advances_past_each_selected_item_even_when_received_at_ties(self):
        a, b, c = self.item(), self.item(), self.item()
        db.InboxItem.update(received_at=a.received_at).where(db.InboxItem.id == b.id).execute()
        self.login("hjalp")
        for selected, expected in [(a, [b.id]), (b, [c.id]), (c, [])]:
            response = self.client.get(f"/api/v2/inkorg?after={selected.id}&mode=mina&order=newest")
            self.assertEqual(response.get_json()["next_untaken"], expected)

    def test_paper_entry_lists_only_available_open_forms_in_queue_order(self):
        self.item()  # certificate only
        theirs, closed, archived, related, mine, free = [self.item() for _ in range(6)]
        db.InboxDocument.update(doc_type="arsblankett").where(
            db.InboxDocument.item.in_([theirs, closed, archived, related, mine, free])
        ).execute()
        inbox.take(theirs, self.manager, over=False)
        inbox.take(mine, self.helper, over=False)
        db.InboxItem.update(state="klar").where(db.InboxItem.id == closed).execute()
        db.InboxDocument.update(done_at=inbox.now()).where(db.InboxDocument.item == archived).execute()
        db.InboxItem.update(ref_type="individual").where(db.InboxItem.id == related).execute()
        db.InboxItem.update(received_at=mine.received_at - timedelta(days=1)).where(db.InboxItem.id == free).execute()
        self.login("hjalp")
        body = self.client.get("/api/v2/inkorg?paper_entry=1").get_json()
        self.assertEqual([item["id"] for item in body["items"]], [free.id, mine.id])
        self.assertEqual(body["total"], 2)

    def test_paper_claim_skips_mixed_item_until_certificate_ready(self):
        mixed, ready = self.item(documents=2), self.item()
        form, certificate = mixed.documents.order_by(db.InboxDocument.id)
        db.InboxDocument.update(doc_type="arsblankett").where(
            db.InboxDocument.id.in_([form.id, ready.documents.get().id])
        ).execute()
        self.login("hjalp")
        queue = "/api/v2/inkorg?paper_entry=1"
        (selected,) = self.client.get(queue).get_json()["items"]
        self.assertEqual(selected["id"], ready.id)
        self.assertEqual(self.post(f"/{selected['id']}/ta", paper_entry=True).status_code, 200)
        self.assertEqual(self.reload(ready).assigned_to_id, self.helper.id)
        self.assertIsNone(self.reload(mixed).assigned_to_id)

        certificate.done_at = inbox.now()
        certificate.save()
        self.assertEqual(self.client.get(queue).get_json()["items"][0]["id"], mixed.id)
        certificate.waiting_for = ["G1-9999"]  # changed after listing, before the claim
        certificate.save()
        self.assertEqual(self.post(f"/{mixed.id}/ta", paper_entry=True).status_code, 409)
        self.assertIsNone(self.reload(mixed).assigned_to_id)

    def test_paper_claim_skips_waiting_and_escalated_forms_after_listing(self):
        self.login("hjalp")
        waiting, escalated = self.item(), self.item()
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item.in_([waiting, escalated])).execute()
        queue = "/api/v2/inkorg?paper_entry=1"
        self.assertEqual(self.client.get(queue).get_json()["total"], 2)
        for item, state in ((waiting, "ofullstandig"), (escalated, "hos_genbanksansvarig")):
            claim = f"/{item.id}/ta"
            self.assertEqual(self.post(claim, paper_entry=True).status_code, 200)
            self.assertIsNone(self.post(claim, paper_entry=True).get_json()["undo"])
            self.assertEqual(self.post(f"/{item.id}/lage", state=state, note="Datum saknas").status_code, 200)
            self.assertEqual(self.post(claim, paper_entry=True).status_code, 409)
            self.assertEqual(self.reload(item).state, state)
        self.assertEqual(self.client.get(queue).get_json()["items"], [])
        self.assertIsNone(self.reload(escalated).assigned_to_id)
        request = db.MailMessage.get(db.MailMessage.kind == "inlasning.ofullstandig")
        self.assertEqual(request.status, "queued")
        self.assertEqual(mail.MAIL_KINDS[request.kind].build(request.params)["note"], "Datum saknas")

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

    def test_opening_is_logged_once_an_hour_per_user_and_item(self):
        item = self.item(0)
        self.login("hjalp")
        for _ in range(3):
            self.client.get(f"/api/v2/inkorg/{item.id}")
        self.login("man")
        self.client.get(f"/api/v2/inkorg/{item.id}")

        def opened():
            return list(
                db.InboxEvent.select().where((db.InboxEvent.item == item.id) & (db.InboxEvent.kind == "oppnad"))
            )

        self.assertEqual(sorted(e.user_id for e in opened()), sorted([self.helper.id, self.manager.id]))
        db.InboxEvent.update(at=inbox.now() - timedelta(minutes=61)).where(
            (db.InboxEvent.kind == "oppnad") & (db.InboxEvent.user == self.helper.id)
        ).execute()
        self.login("hjalp")
        self.client.get(f"/api/v2/inkorg/{item.id}")
        self.assertEqual(len(opened()), 3)


class TestTakeAndAssign(InboxTest):
    def test_takeover_requires_the_displayed_handler_and_assignment_time(self):
        item = self.item()
        inbox.take(item, self.helper, over=False)
        self.login("man")
        path = f"/api/v2/inkorg/{item.id}"
        shown = self.client.get(path).get_json()
        expected = {"assigned_to": shown["assigned_to"]["id"], "assigned_at": shown["assigned_at"]}

        def refused(stale):
            response = self.client.put(f"{path}/ta-over", json=stale)
            self.assertEqual(response.status_code, 409)
            self.assertIn("Tilldelningen har ändrats", response.get_json()["detail"])

        inbox.assign(item, self.manager, self.manager)
        refused({**expected, "assigned_at": self.client.get(path).get_json()["assigned_at"]})
        self.assertEqual(self.reload(item).assigned_to_id, self.manager.id)
        inbox.assign(item, self.manager, self.helper)
        refused(expected)  # back with the displayed handler, under a new assignment
        self.assertEqual(self.reload(item).assigned_to_id, self.helper.id)
        self.assertFalse(item.events.where(db.InboxEvent.kind == "overtagen").exists())
        current = self.client.get(path).get_json()
        response = self.client.put(f"{path}/ta-over", json={**expected, "assigned_at": current["assigned_at"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reload(item).assigned_to_id, self.manager.id)

    def test_only_actor_undoes_a_take_and_a_view_does_not_invalidate_it(self):
        item = self.item()
        self.login("hjalp")
        token = self.post(f"/{item.id}/ta").get_json()["undo"]
        self.assertIsNone(self.post(f"/{item.id}/ta").get_json()["undo"])
        self.client.get(f"/api/v2/inkorg/{item.id}")
        self.login("man")
        self.assertEqual(self.post("/angra", undo=token).status_code, 403)
        self.login("hjalp")
        self.assertEqual(self.post("/angra", undo="ogiltig").status_code, 400)
        self.assertEqual(self.post("/angra", undo=token).get_json(), {"restored": [item.id]})
        self.assertEqual(self.reload(item).state_changed_at, item.state_changed_at)
        self.assertIsNone(self.reload(item).assigned_to_id)
        self.assertEqual(self.post("/angra", undo=token).status_code, 409)

    def test_undo_takeover_and_release_restore_prior_handler_and_waiting_state(self):
        item = self.item()
        inbox.take(item, self.helper, over=False)
        item.state = "vantar_uppfodare"
        item.save()
        self.login("man")
        self.assertEqual(self.post(f"/{item.id}/slapp").status_code, 409)
        takeover = self.post(f"/{item.id}/ta-over").get_json()
        self.assertEqual(self.post("/angra", undo=takeover["undo"]).status_code, 200)
        self.assertFalse(db.Notice.select().where(db.Notice.kind == "overtagen").exists())
        previous = self.reload(item)
        self.assertEqual((previous.state, previous.assigned_to_id), ("vantar_uppfodare", self.helper.id))
        self.login("hjalp")
        for state in ("vantar_uppfodare", "vantar_foralder", "ofullstandig"):
            db.InboxItem.update(state=state).where(db.InboxItem.id == item.id).execute()
            refused = self.post(f"/{item.id}/slapp")
            self.assertEqual(refused.status_code, 409)
            self.assertIn("väntar", refused.get_json()["detail"])
            self.assertEqual(self.reload(item).state, state)
        db.InboxItem.update(state="tagen").where(db.InboxItem.id == item.id).execute()
        previous = self.reload(item)
        released = self.post(f"/{item.id}/slapp").get_json()
        self.assertEqual((released["state"], released["assigned_to"]), ("ny", None))
        self.assertEqual(self.post("/angra", undo=released["undo"]).status_code, 200)
        restored = self.reload(item)
        self.assertEqual((restored.state, restored.assigned_at), (previous.state, previous.assigned_at))

    def test_preview_and_batch_undo_cover_the_whole_herd_or_nothing(self):
        first, second = self.item(), self.item()
        self.item(1)
        inbox.take(second, self.helper, over=False)
        self.login("hjalp")
        self.assertEqual(self.client.get("/api/v2/inkorg/tilldela?herd=G1").status_code, 403)
        self.login("man")

        def preview():
            return self.client.get("/api/v2/inkorg/tilldela?herd=G1").get_json()

        def assign(revision):
            return self.post("/tilldela", herd="G1", user_id=self.manager.id, revision=revision)

        before = preview()
        self.assertEqual(before["total"], 2)
        self.assertEqual([(p["id"], p["count"]) for p in before["assignees"]], [(self.helper.id, 1)])
        third = self.item()
        self.assertEqual(assign(before["revision"]).status_code, 409)
        self.assertIsNone(self.reload(first).assigned_to_id)
        batch = assign(preview()["revision"]).get_json()
        self.assertEqual(batch["assigned"], [first.id, second.id, third.id])
        self.assertEqual(self.post("/angra", undo=batch["undo"]).get_json(), {"restored": batch["assigned"]})
        self.assertEqual([self.reload(i).assigned_to_id for i in (first, second, third)], [None, self.helper.id, None])

        batch = assign(preview()["revision"]).get_json()
        self.login("hjalp")
        self.post(f"/{third.id}/ta-over")
        self.login("man")
        self.assertEqual(self.post("/angra", undo=batch["undo"]).status_code, 409)
        self.assertEqual([self.reload(i).assigned_to_id for i in (first, second)], [self.manager.id, self.manager.id])
        self.assertEqual(self.reload(third).assigned_to_id, self.helper.id)

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
        held = self.item(0)
        held.ref_data = {inbox.PURPOSE: inbox.HELD_RABBIT}
        held.save()
        inbox.take(closed, self.helper, over=False)
        inbox.change_state(closed, self.helper, "skrap")
        self.login("man")
        refused = self.post("/tilldela", herd="G1", user_id=self.helper.id)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("revision", refused.get_json()["detail"])
        self.assertIsNone(self.reload(first).assigned_to_id)
        preview = self.client.get("/api/v2/inkorg/tilldela?herd=G1").get_json()
        self.assertEqual(preview["total"], 2)
        resp = self.post("/tilldela", herd="G1", user_id=self.helper.id, revision=preview["revision"])
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["assigned"], [first.id, second.id])
        self.assertIsNone(self.reload(held).assigned_to_id)
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

    def test_a_state_that_is_not_text_is_a_bad_request(self):
        item = self.at("tagen")
        self.login("hjalp")
        for state in (["skrap"], {"a": 1}, 7, None):
            with self.subTest(state=state):
                self.assertEqual(self.post(f"/{item.id}/lage", state=state).status_code, 400)
        self.assertEqual(self.reload(item).state, "tagen")

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

    def test_a_message_is_closed_as_answered(self):
        item = self.at("tagen")
        db.InboxItem.update(kind="meddelande").where(db.InboxItem.id == item.id).execute()
        self.login("hjalp")
        resp = self.post(f"/{item.id}/lage", state="klar", note="Besvarat i telefon")
        self.assertEqual(resp.status_code, 409, resp.get_json())  # a photo that came with an answer is still open
        db.InboxDocument.delete().where(db.InboxDocument.item == item.id).execute()

        resp = self.post(f"/{item.id}/lage", state="klar", note="Besvarat i telefon")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["state"], "klar")
        self.assertIsNotNone(resp.get_json()["closed_at"])
        event = db.InboxEvent.select().where(db.InboxEvent.kind == "lage").get()
        self.assertEqual(event.detail, {"from": "tagen", "to": "klar", "note": "Besvarat i telefon"})
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.kind == "inlasning.klar").exists())

    def test_an_item_without_documents_is_closed_as_answered_whatever_its_kind(self):
        self.login("hjalp")
        for state in inbox.HELD_STATES:
            with self.subTest(state):
                item = self.at(state)
                db.InboxItem.update(kind="mail").where(db.InboxItem.id == item.id).execute()
                db.InboxDocument.delete().where(db.InboxDocument.item == item.id).execute()  # all skipped
                resp = self.post(f"/{item.id}/lage", state="klar")
                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertEqual(resp.get_json()["state"], "klar")
        with_document = self.at("tagen")
        self.assertEqual(self.post(f"/{with_document.id}/lage", state="klar").status_code, 400)

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
            self.patch(item, document, mask_rects=None).get_json()["document"]["frame_suggestion"],
            inbox.HANDWRITTEN_FRAME,
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

    def test_my_uploads_leave_out_a_held_photo_of_every_purpose(self):
        sent = self.item(0)
        held = [self.item(0) for _ in (*inbox.PURPOSES, inbox.HELD_RABBIT)]
        for item, purpose in zip(held, (*inbox.PURPOSES, inbox.HELD_RABBIT), strict=True):
            item.ref_data = {inbox.PURPOSE: purpose}
            item.save()
        self.login("owner")
        ids = [i["id"] for i in self.client.get("/api/v2/inkorg/mina-inskick").get_json()["items"]]
        self.assertEqual(ids, [sent.id])

    def test_the_list_reads_no_notice_and_the_page_marks_them_seen(self):
        mine = self.item(0)
        inbox.notify(self.owner, "klar", mine)
        inbox.notify(self.owner, "svar", mine)
        inbox.notify(self.manager, "klar", mine)
        self.assertEqual(self.client.post("/api/v2/inkorg/mina-inskick/sedda").status_code, 401)
        self.login("owner")

        def unread():
            rows = db.Notice.select().where((db.Notice.user == self.owner.id) & db.Notice.read_at.is_null(True))
            return sorted(row.kind for row in rows)

        for method in (self.client.get, self.client.head):  # a link to the list changes nothing
            self.assertEqual(method("/api/v2/inkorg/mina-inskick").status_code, 200)
        self.assertEqual(unread(), ["klar", "svar"])
        resp = self.client.post("/api/v2/inkorg/mina-inskick/sedda")
        self.assertEqual((resp.status_code, resp.get_json()), (200, {"read": 1}))
        self.assertEqual(unread(), ["svar"])
        self.assertEqual(self.client.post("/api/v2/inkorg/mina-inskick/sedda").get_json(), {"read": 0})
        theirs = db.Notice.get((db.Notice.user == self.manager.id) & (db.Notice.kind == "klar"))
        self.assertIsNone(theirs.read_at)

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
