import unittest
from unittest.mock import patch

from nistiprint_shared.services.demanda.core import DemandaCoreService


class FakeQuery:
    def __init__(self, table_name, rows_by_table):
        self.table_name = table_name
        self.rows_by_table = rows_by_table
        self.in_filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, field, values):
        self.in_filters[field] = set(values)
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows = list(self.rows_by_table.get(self.table_name, []))
        for field, values in self.in_filters.items():
            rows = [row for row in rows if isinstance(row, dict) and row.get(field) in values]
        return type('Result', (), {'data': rows})()


class TestDemandaCoreAggregationResilience(unittest.TestCase):
    def test_get_aggregated_demandas_ignores_invalid_rows(self):
        rows_by_table = {
            'itens_demanda': [
                {'demanda_id': 1, 'quantidade': 5},
                None,
            ],
            'entrega_producao': [
                {'demanda_id': 1, 'quantidade': 3},
                None,
                {'demanda_id': None, 'quantidade': 9},
            ],
        }

        def table_side_effect(name):
            return FakeQuery(name, rows_by_table)

        with patch('nistiprint_shared.services.demanda.core.supabase_db.table') as table_mock, \
             patch('nistiprint_shared.services.demanda.core.supabase_db.execute_with_retry') as retry_mock:
            table_mock.side_effect = table_side_effect
            retry_mock.side_effect = lambda query: query.execute()

            service = DemandaCoreService()
            response_data = [
                None,
                {'status': 'EM_PRODUCAO'},
                {'id': 1, 'status': 'EM_PRODUCAO', 'descricao': 'Demanda Teste', 'canal_venda': None},
                'invalid',
            ]
            result = service._get_aggregated_demandas(response_data)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 1)
        self.assertEqual(result[0]['quantidade_coletada_total'], 3)


if __name__ == '__main__':
    unittest.main()
