import unittest
from unittest.mock import patch

from nistiprint_shared.services.demanda.items import DemandaItemsService


class ProductionDecreaseGuardTests(unittest.TestCase):
    def test_incremental_reduction_fails_before_persisting_visual_intent(self):
        service = DemandaItemsService()
        item = {'id': 15, 'finalizados_qtd': 4, 'quantidade': 10}
        with patch.object(service, 'get_item_by_id', return_value=item), \
             patch.object(service, 'atualizar_progresso_item') as persist:
            with self.assertRaisesRegex(ValueError, 'REQUER_COMPENSACAO'):
                service.registrar_producao_incremental(
                    '2', 15, {'finalizados_qtd': -1}, user_id=7
                )
        persist.assert_not_called()


if __name__ == '__main__':
    unittest.main()
