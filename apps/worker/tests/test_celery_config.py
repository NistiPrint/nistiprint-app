import sys
from pathlib import Path
from unittest import TestCase


WORKER_DIR = Path(__file__).resolve().parents[1]
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

import celery_config  # noqa: E402


class CeleryConfigTest(TestCase):
    def test_default_schedules_use_unified_app_managed_renewal_task(self):
        schedules = celery_config.get_default_schedules()

        self.assertIn("renew-app-managed-credentials", schedules)
        self.assertEqual(
            schedules["renew-app-managed-credentials"]["task"],
            "tasks.token_renewal_tasks.renew_app_managed_credentials",
        )
        self.assertEqual(
            schedules["renew-app-managed-credentials"]["schedule"],
            7200,
        )
        self.assertNotIn("renew-shopee-tokens", schedules)
