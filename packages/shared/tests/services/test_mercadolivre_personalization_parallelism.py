import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from nistiprint_shared.services import mercadolivre_personalization_service as service


class MercadoLivrePersonalizationParallelismTests(unittest.TestCase):
    def test_each_account_runs_at_most_ten_packs_and_refills_available_slots(self):
        lock = threading.Lock()
        started = {7: 0, 8: 0}
        active = {7: 0, 8: 0}
        maximum = {7: 0, 8: 0}
        ten_started = threading.Event()
        release = threading.Event()

        def process_pack(integration_id, pack_id, **_kwargs):
            with lock:
                active[integration_id] += 1
                started[integration_id] += 1
                maximum[integration_id] = max(maximum[integration_id], active[integration_id])
                if all(value == 10 for value in active.values()):
                    ten_started.set()
            release.wait(timeout=3)
            with lock:
                active[integration_id] -= 1
            return {"status": "success", "pack_id": pack_id}

        def run(integration_id):
            items = [{"pack_id": str(index)} for index in range(11)]
            return list(service._iter_pack_results(
                integration_id, "batch", items, False, {}, "run-token",
            ))

        with patch.object(service, "process_pack", side_effect=process_pack):
            with ThreadPoolExecutor(max_workers=2) as caller_pool:
                first = caller_pool.submit(run, 7)
                second = caller_pool.submit(run, 8)
                self.assertTrue(ten_started.wait(timeout=2))
                with lock:
                    self.assertEqual(active[7] + active[8], 20)
                    self.assertEqual(maximum, {7: 10, 8: 10})
                release.set()
                self.assertEqual(len(first.result(timeout=4)), 11)
                self.assertEqual(len(second.result(timeout=4)), 11)

        self.assertEqual(started, {7: 11, 8: 11})
        self.assertEqual(maximum, {7: 10, 8: 10})


if __name__ == "__main__":
    unittest.main()
