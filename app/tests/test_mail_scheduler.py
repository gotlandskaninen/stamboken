"""The mail queue's scheduler jobs: mail_send every 30 s on the leader, and the purge in the 03:30 job.

isort:skip_file
"""

import os
import tempfile
from datetime import timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import herdbook  # noqa: E402
import utils.cache_invalidation as ci  # noqa: E402
import utils.database as db  # noqa: E402

from tests.test_mail_queue import MailTest  # noqa: E402


class TestMailJobs(MailTest):
    def test_send_job_sends_and_closes_its_connection(self):
        row_id = self.queue()
        self.relay()
        with mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close:
            herdbook._send_mail()
        self.assertEqual(self.row(row_id).status, "sent")
        close.assert_called_once()

        with (
            mock.patch.object(herdbook, "send_pending", side_effect=RuntimeError("database gone")),
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
            self.assertLogs(herdbook.APP.logger, "ERROR"),
        ):
            herdbook._send_mail()  # logged, never raised into the scheduler
        close.assert_called_once()

    def test_nightly_job_purges_the_queue_even_when_the_other_purge_fails(self):
        old = self.queue()
        db.MailMessage.update(created_at=self.now - timedelta(days=400)).where(db.MailMessage.id == old).execute()
        with (
            mock.patch.object(herdbook, "purge_command_free_text", side_effect=RuntimeError("database gone")),
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
            self.assertRaises(RuntimeError),
        ):
            herdbook._purge_command_free_text()
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.id == old).exists())
        close.assert_called_once()

    def test_leader_registers_mail_send(self):
        lock = os.path.join(tempfile.mkdtemp(), "scheduler.lock")
        with (
            mock.patch.object(herdbook, "SCHEDULER_LOCK_PATH", lock),
            mock.patch.object(ci, "init_redis"),
            mock.patch.object(ci, "start_pubsub_listener"),
            mock.patch.object(ci, "set_cache_and_functions"),
            mock.patch.object(herdbook, "_warm_genetics_in_background"),
            mock.patch.object(herdbook.gblogging, "create_genebank_logs"),
            mock.patch.object(herdbook.apscheduler.schedulers.background, "BackgroundScheduler") as scheduler_cls,
        ):
            herdbook.initialize_app()
        (job,) = [c for c in scheduler_cls.return_value.add_job.call_args_list if herdbook._send_mail in c.args]
        self.assertEqual(
            {k: job.kwargs[k] for k in ("trigger", "seconds", "id", "max_instances", "coalesce")},
            {"trigger": "interval", "seconds": 30, "id": "mail_send", "max_instances": 1, "coalesce": True},
        )
