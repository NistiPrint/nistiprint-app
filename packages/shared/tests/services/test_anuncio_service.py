import unittest
from unittest.mock import MagicMock

from nistiprint_shared.services.anuncio_service import AnuncioService


class AnuncioServiceTests(unittest.TestCase):
    def test_list_groups_sellable_units_under_account_scoped_headers(self):
        db = MagicMock()
        headers = [{'id': 8, 'integration_id': 2, 'item_externo_id': 'ML-1'}]
        units = [{'id': 30, 'anuncio_id': 8, 'produto_id': 4}]
        query = MagicMock()
        query.execute.return_value.data = headers
        query.execute.return_value.count = 1
        db.table.return_value.select.return_value.order.return_value.eq.return_value.range.return_value = query
        db.table.return_value.select.return_value.in_.return_value.order.return_value.execute.return_value.data = units
        result = AnuncioService(db).list(integration_id=2)
        self.assertEqual(result['rows'][0]['unidades'], units)
        self.assertEqual(result['total'], 1)


if __name__ == '__main__':
    unittest.main()
