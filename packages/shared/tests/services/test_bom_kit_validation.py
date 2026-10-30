import unittest
from unittest.mock import MagicMock, patch
from nistiprint_shared.services.bom_service import BomService


class KitComponentTests(unittest.TestCase):
    def validate(self, parent, component):
        with patch('nistiprint_shared.services.bom_service.product_service') as products:
            products.get_by_id.side_effect = [component, parent]
            return BomService._validate_component_can_be_used(object(), 2, 1)

    def test_finished_product_is_allowed_in_kit(self):
        component = {'id': 2, 'tipo_produto': 'PRODUTO_ACABADO', 'formato': 'composicao'}
        self.assertEqual(self.validate({'formato': 'kit'}, component), component)

    def test_finished_product_is_rejected_in_manufacturing(self):
        with self.assertRaises(ValueError):
            self.validate({'formato': 'composicao'}, {'tipo_produto': 'PRODUTO_ACABADO'})

    def test_kit_rejects_raw_material_and_nested_kit(self):
        for component in ({'tipo_produto': 'MATERIA_PRIMA'}, {'tipo_produto': 'PRODUTO_ACABADO', 'formato': 'kit'}):
            with self.subTest(component=component), self.assertRaises(ValueError):
                self.validate({'formato': 'kit'}, component)

    def test_partial_import_does_not_reprice_or_enqueue_costs(self):
        with patch('nistiprint_shared.services.bom_service.supabase_db') as db, patch('nistiprint_shared.services.bom_service.product_service') as products:
            products.get_by_id.return_value = {'id': 1, 'formato': 'composicao', 'tipo_produto': 'MATERIA_PRIMA'}
            db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
            service = BomService()
            service._update_cost_and_enqueue_cascade = MagicMock()
            service.add_bom_component(1, 2, 1, recalculate_cost=False)
            service._update_cost_and_enqueue_cascade.assert_not_called()
            service.bom_table.insert.assert_called_once()
