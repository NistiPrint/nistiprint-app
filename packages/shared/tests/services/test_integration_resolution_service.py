import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.integration_resolution_service import IntegrationResolutionService


class TestIntegrationResolutionService(unittest.TestCase):
    def setUp(self):
        self.service = IntegrationResolutionService(ttl_seconds=9999)

    def _mock_supabase_tables(self, integrations, modules):
        def table_side_effect(name):
            table = MagicMock()
            if name == 'installed_integrations':
                table.select.return_value.eq.return_value.execute.return_value.data = integrations
                return table
            if name == 'integration_modules':
                table.select.return_value.execute.return_value.data = modules
                return table
            raise AssertionError(f"unexpected table: {name}")

        return table_side_effect

    def test_resolve_marketplace_by_multiple_shop_aliases_and_scope(self):
        integrations = [
            {
                'id': 10,
                'module_id': 'mod-shopee',
                'instance_name': 'Shopee Loja 1',
                'config': {
                    'shop_ids': ['204047801', '205218967'],
                    'bling_integration_ids': [1],
                },
                'credentials': {},
                'is_active': True,
            },
            {
                'id': 11,
                'module_id': 'mod-shopee',
                'instance_name': 'Shopee Loja 2',
                'config': {
                    'bling_loja_ids': ['205218967'],
                    'bling_integration_ids': [2],
                },
                'credentials': {},
                'is_active': True,
            },
        ]
        modules = [{'id': 'mod-shopee', 'slug': 'shopee', 'tipo': 'marketplace', 'name': 'Shopee'}]

        with patch('nistiprint_shared.services.integration_resolution_service.supabase_db.table') as table_mock:
            table_mock.side_effect = self._mock_supabase_tables(integrations, modules)
            self.service.invalidate()

            result_scoped = self.service.resolve_marketplace_by_shop_id('205218967', bling_integration_id=2)
            result_fallback = self.service.resolve_marketplace_by_shop_id('204047801', bling_integration_id=99)

        self.assertEqual(result_scoped['id'], 11)
        self.assertEqual(result_fallback['id'], 10)

    def test_resolve_bling_by_company_aliases(self):
        integrations = [
            {
                'id': 20,
                'module_id': 'mod-bling',
                'instance_name': 'Bling 01',
                'config': {
                    'company_ids': ['fa3c40c3e6ec60129f2c1a063872b816', 'alias-2'],
                    'cnpj': '12345678000199',
                },
                'credentials': {},
                'is_active': True,
            }
        ]
        modules = [{'id': 'mod-bling', 'slug': 'bling', 'tipo': 'erp', 'name': 'Bling'}]

        with patch('nistiprint_shared.services.integration_resolution_service.supabase_db.table') as table_mock:
            table_mock.side_effect = self._mock_supabase_tables(integrations, modules)
            self.service.invalidate()

            by_company = self.service.resolve_bling_by_company_id('alias-2')
            by_cnpj = self.service.resolve_bling_by_cnpj('BR-12345678000199')

        self.assertEqual(by_company['id'], 20)
        self.assertEqual(by_cnpj['id'], 20)


if __name__ == '__main__':
    unittest.main()
