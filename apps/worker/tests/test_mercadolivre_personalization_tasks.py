import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from nistiprint_shared.services import mercadolivre_personalization_worker as tasks


class MercadoLivreCeleryTaskTests(unittest.TestCase):
    def test_ingestion_task_only_calls_message_inbox_processor(self):
        expected = {"claimed": 1, "synced": 1, "retried": 0, "failed": 0}
        with patch("nistiprint_shared.services.mercadolivre_personalization_service.process_inbox_once",
                   return_value=expected) as process_inbox, \
             patch.object(tasks, "_run_logged_task", side_effect=lambda _name, _request, _origin, fn,
                          **_kwargs: fn()):
            result = tasks.process_chat_inbox.run(limit=8)
        self.assertEqual(result, expected)
        process_inbox.assert_called_once_with(limit=8)

    def test_account_daily_job_uses_integration_lock_and_enqueues_batch_once(self):
        local_now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        current = {"enabled": True, "extraction_enabled": True, "schedule_enabled": True,
                   "schedule_hour": 9, "schedule_minute": 0,
                   "last_scheduled_run_date": "2026-10-06", "max_processing": 20}
        lock = Mock()
        lock.acquire.side_effect = [True, False]
        fake_redis = Mock()
        fake_redis.lock.return_value = lock
        queued = {"batch_id": "batch-1", "total": 2}
        with patch.object(tasks, "_now", return_value=local_now), \
             patch.object(tasks, "_redis_client", return_value=fake_redis), \
             patch("nistiprint_shared.services.mercadolivre_personalization_service._settings",
                   return_value=current), \
             patch("nistiprint_shared.services.mercadolivre_personalization_service._queue_packs",
                   return_value=queued) as queue_packs, \
             patch("nistiprint_shared.database.supabase_db_service.supabase_db") as db, \
             patch.object(tasks, "_run_logged_task", side_effect=lambda _name, _request, _origin, fn,
                          **_kwargs: fn()), \
             patch.object(tasks.process_personalization_batch, "apply_async") as dispatch_batch:
            first = tasks.run_due_personalization.run(7)
            second = tasks.run_due_personalization.run(7)

        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "already_running")
        self.assertEqual(fake_redis.lock.call_args.args[0],
                         "np:ml-personalization:daily-lock:7:2026-10-07")
        queue_packs.assert_called_once_with(7, limit=20)
        dispatch_batch.assert_called_once_with(args=[7, "batch-1"], queue="celery")
        db.table.assert_called_once_with("mercadolivre_personalization_config")

    def test_batch_manual_dispatch_uses_shared_default_queue(self):
        with patch("nistiprint_shared.services.celery_app.celery_app.send_task") as send_task:
            tasks.submit_batch(12, "batch-abc")
        send_task.assert_called_once_with(
            tasks.TASK_PROCESS_BATCH, args=[12, "batch-abc"], queue="celery",
        )

    def test_schedule_due_is_per_account_and_respects_pause(self):
        now = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
        self.assertTrue(tasks._is_schedule_due({
            "enabled": True, "extraction_enabled": True, "schedule_enabled": True,
            "schedule_hour": 9, "schedule_minute": 30,
            "last_scheduled_run_date": "2026-10-06",
        }, now))
        self.assertFalse(tasks._is_schedule_due({
            "enabled": True, "extraction_enabled": True, "schedule_enabled": False,
            "schedule_hour": 9, "schedule_minute": 0,
        }, now))


if __name__ == "__main__":
    unittest.main()
