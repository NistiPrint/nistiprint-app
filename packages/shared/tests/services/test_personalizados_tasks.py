import unittest
from unittest.mock import patch

from nistiprint_shared.services import personalizados_tasks


class TestPersonalizadosTask(unittest.TestCase):
    def test_pre_count_uses_processing_candidates_not_display_orders(self):
        with patch(
            "nistiprint_shared.services.ai_personalization_service.select_orders_for_processing",
            return_value=([], []),
        ) as select, patch(
            "nistiprint_shared.services.ai_personalization_service.process_orders"
        ) as process:
            result = personalizados_tasks.processar_personalizacoes_task.run(
                order_sn="SN-123"
            )

        select.assert_called_once_with(order_sn="SN-123", limit=None)
        process.assert_not_called()
        self.assertEqual(result["processed"], 0)

    def test_processes_only_the_preselected_candidates(self):
        candidates = [{"id": 2, "order_sn": "SN-123"}]
        with patch(
            "nistiprint_shared.services.ai_personalization_service.select_orders_for_processing",
            return_value=(candidates, []),
        ) as select, patch(
            "nistiprint_shared.services.ai_personalization_service.process_orders",
            return_value=(True, "Agendado", {"total": 1}),
        ) as process:
            result = personalizados_tasks.processar_personalizacoes_task.run(
                order_sn="SN-123"
            )

        select.assert_called_once_with(order_sn="SN-123", limit=None)
        process.assert_called_once_with(order_sn="SN-123", limit=None)
        self.assertEqual(result["total_processed"], 1)


if __name__ == "__main__":
    unittest.main()
