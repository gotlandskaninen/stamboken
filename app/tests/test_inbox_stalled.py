"""The nightly flag "står still" on an item taken 14 days ago with nothing happening since, and its one notice.

isort:skip_file
"""

from datetime import timedelta

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.inbox_purge as purge  # noqa: E402

from tests.test_inbox_purge import MINUTE, NOW, PurgeTest  # noqa: E402

SINCE = NOW - timedelta(days=14)


class TestStalled(PurgeTest):
    def taken(self, changed_at, state="tagen"):
        item = self.make(state=state)
        db.InboxItem.update(state_changed_at=changed_at, assigned_to=self.helper).where(
            db.InboxItem.id == item.id
        ).execute()
        return item

    def notices(self):
        return [(n.user_id, n.item_id) for n in db.Notice.select().where(db.Notice.kind == "star_still")]

    def test_a_taken_item_stalls_after_14_days_and_the_managers_hear_it_once(self):
        fresh = self.taken(SINCE + MINUTE)
        stalled = self.taken(SINCE - MINUTE)
        waiting = self.taken(SINCE - MINUTE, state="vantar_uppfodare")
        viewed = self.taken(SINCE - MINUTE)
        db.InboxEvent.create(item=viewed, user=self.manager, kind="oppnad", at=NOW - MINUTE)  # looking is no event
        worked = self.taken(SINCE - MINUTE)
        db.InboxEvent.create(item=worked, user=self.helper, kind="dokument", at=SINCE + MINUTE)

        self.assertEqual(purge.mark_stalled(NOW), 2)

        flagged = {i.id for i in db.InboxItem.select().where(db.InboxItem.stalled)}
        self.assertEqual(flagged, {stalled.id, viewed.id})
        self.assertNotIn(fresh.id, flagged)
        self.assertNotIn(waiting.id, flagged)
        self.assertEqual(sorted(self.notices()), sorted([(self.manager.id, stalled.id), (self.manager.id, viewed.id)]))
        self.assertTrue(inbox.items_json([self.reload(stalled)])[0]["stalled"])
        self.assertIdempotent(purge.mark_stalled)

    def test_the_flag_goes_when_something_happens_and_a_new_stall_is_told_again(self):
        item = self.taken(SINCE - MINUTE)
        purge.mark_stalled(NOW)
        db.InboxEvent.create(item=item, user=self.helper, kind="dokument", at=NOW - timedelta(days=1))

        purge.mark_stalled(NOW)
        self.assertFalse(self.reload(item).stalled)

        purge.mark_stalled(NOW + timedelta(days=14))
        self.assertTrue(self.reload(item).stalled)
        self.assertEqual(self.notices(), [(self.manager.id, item.id)] * 2)

    def test_the_nightly_job_flags(self):
        item = self.taken(SINCE - MINUTE)
        purge.run(NOW)
        self.assertTrue(self.reload(item).stalled)
