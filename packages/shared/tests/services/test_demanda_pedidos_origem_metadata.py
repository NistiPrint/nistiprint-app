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

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def in_(self, field, values):
        self.in_filters[field] = set(values)
        return self

    def execute(self):
        rows = list(self.rows_by_table.get(self.table_name, []))
        for field, values in self.in_filters.items():
            rows = [row for row in rows if row.get(field) in values]
        return type('Result', (), {'data': rows})()


class TestDemandaPedidosOrigemMetadata(unittest.TestCase):
    def test_returns_origin_orders_chunks_and_bling_groups(self):
        pivot_rows = [{'pedido_id': idx} for idx in range(1, 102)]
        pedidos = [
            {
                'id': idx,
                'numero_pedido': f'N{idx}',
                'codigo_pedido_externo': f'EXT{idx}',
                'origem': 'bling',
                'cliente_nome': f'Cliente {idx}',
                'canal_venda_id': 7,
                'situacao_pedido_id': 1,
                'data_venda': '2026-05-13',
                'total_pedido': 10,
                'is_flex': False,
                'bling_integration_id': 10 if idx <= 100 else 20,
                'marketplace_integration_id': None,
                'pedido_bling_id': 1000 + idx,
            }
            for idx in range(1, 102)
        ]
        pedidos_bling = [
            {
                'id': 1000 + idx,
                'bling_id': 9000 + idx,
                'numero_pedido': f'B{idx}',
                'numero_loja': f'EXT{idx}',
                'bling_integration_id': 10 if idx <= 100 else 20,
                'raw_payload': {},
            }
            for idx in range(1, 102)
        ]
        rows_by_table = {
            'demandas_pedidos': pivot_rows,
            'pedidos': pedidos,
            'pedidos_bling': pedidos_bling,
            'installed_integrations': [
                {'id': 10, 'instance_name': 'Bling Principal'},
                {'id': 20, 'instance_name': 'Bling Secundario'},
            ],
        }

        def table_side_effect(name):
            return FakeQuery(name, rows_by_table)

        with patch('nistiprint_shared.services.demanda.core.supabase_db.table') as table_mock:
            table_mock.side_effect = table_side_effect
            service = DemandaCoreService()
            result = service._get_pedidos_origem_metadata(123)

        self.assertEqual(len(result['pedidos_origem']), 101)
        self.assertEqual(len(result['pedidos_origem_chunks']), 2)
        self.assertEqual(len(result['pedidos_origem_chunks'][0].split(';')), 100)
        self.assertEqual(result['pedidos_origem_chunks'][1], 'EXT101')

        groups = result['pedidos_origem_por_bling']
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['account_label'], 'Bling Principal')
        self.assertEqual(len(groups[0]['pedidos']), 100)
        self.assertEqual(groups[1]['account_label'], 'Bling Secundario')
        self.assertEqual(len(groups[1]['pedidos']), 1)


if __name__ == '__main__':
    unittest.main()
