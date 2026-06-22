import sys
import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch


WORKER_DIR = Path(__file__).resolve().parents[1]
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

MODULE_PATH = WORKER_DIR / "tasks" / "token_renewal_tasks.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "token_renewal_tasks_under_test",
    MODULE_PATH,
)
token_renewal_tasks = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(token_renewal_tasks)


class TokenRenewalTasksTest(TestCase):
    def _mock_task_logger_table(self):
        table = MagicMock()
        table.insert.return_value.execute.return_value.data = [{"id": 1}]
        table.update.return_value.eq.return_value.execute.return_value.data = []
        return table

    def test_unified_task_delegates_to_token_renewal_service(self):
        with patch(
            "task_logger.supabase_db.table",
            return_value=self._mock_task_logger_table(),
        ), patch.object(
            token_renewal_tasks.token_renewal_service,
            "renew_app_managed_credentials",
            return_value={"status": "SUCCESS", "renewed": 2},
        ) as renew:
            result = token_renewal_tasks.renew_app_managed_credentials_task.run()

        renew.assert_called_once_with()
        self.assertEqual(result["renewed"], 2)

    def test_legacy_shopee_wrapper_delegates_with_module_filter(self):
        with patch(
            "task_logger.supabase_db.table",
            return_value=self._mock_task_logger_table(),
        ), patch.object(
            token_renewal_tasks.token_renewal_service,
            "renew_app_managed_credentials",
            return_value={"status": "SUCCESS", "renewed": 1},
        ) as renew:
            result = token_renewal_tasks.renew_shopee_tokens_task.run()

        renew.assert_called_once_with(module_filter="shopee")
        self.assertEqual(result["renewed"], 1)

    def test_legacy_mercadolivre_wrapper_delegates_with_module_filter(self):
        with patch(
            "task_logger.supabase_db.table",
            return_value=self._mock_task_logger_table(),
        ), patch.object(
            token_renewal_tasks.token_renewal_service,
            "renew_app_managed_credentials",
            return_value={"status": "SUCCESS", "renewed": 1},
        ) as renew:
            result = token_renewal_tasks.renew_mercadolivre_tokens_task.run()

        renew.assert_called_once_with(module_filter="mercadolivre")
        self.assertEqual(result["renewed"], 1)
