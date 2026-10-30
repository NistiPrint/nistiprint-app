import unittest
from unittest.mock import MagicMock

from nistiprint_shared.services.anuncio_service import AnuncioService


class RelationshipTests(unittest.TestCase):
    def test_filter_reads_all_pages_and_excludes_legacy_headers(self):
        db = MagicMock()
        query = db.table.return_value
        query.select.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.range.return_value = query
        query.execute.side_effect = [
            MagicMock(data=[{'id': i, 'anuncio_id': i, 'produto_id': None} for i in range(500)]),
            MagicMock(data=[{'id': 501, 'anuncio_id': 501, 'produto_id': None},
                            {'id': 502, 'anuncio_id': None, 'produto_id': None},
                            {'id': 503, 'anuncio_id': 503, 'produto_id': 8}]),
        ]
        ids = AnuncioService(db)._relationship_ids('unlinked', 6)
        self.assertEqual(len(ids), 501)
        self.assertIn(501, ids)
        self.assertNotIn(None, ids)
        self.assertNotIn(503, ids)
        query.eq.assert_called_with('integration_id', 6)

    def test_invalid_relationship_is_rejected(self):
        db = MagicMock()
        with self.assertRaises(ValueError):
            AnuncioService(db).list(relationship='unknown')
        db.table.assert_not_called()

    def test_review_uses_pending_primary_key_and_account(self):
        db = MagicMock()
        pending = MagicMock()
        units = MagicMock()
        db.table.side_effect = lambda name: pending if name == 'marketplace_anuncio_pendencias' else units
        pending.select.return_value = pending
        pending.is_.return_value = pending
        pending.eq.return_value = pending
        pending.order.return_value = pending
        pending.range.return_value = pending
        pending.execute.return_value.data = [{'unidade_id': 12}]
        units.select.return_value.in_.return_value.execute.return_value.data = [{'anuncio_id': 7}]
        self.assertEqual(AnuncioService(db)._relationship_ids('review', 6), {7})
        pending.select.assert_called_with('unidade_id')
        pending.order.assert_called_with('unidade_id')
        pending.eq.assert_called_with('integration_id', 6)

    def test_empty_filter_preserves_accounts(self):
        service = AnuncioService(MagicMock())
        service._relationship_ids = MagicMock(return_value=set())
        service.accounts = MagicMock(return_value=[{'id': 6}])
        result = service.list(relationship='review')
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['accounts'], [{'id': 6}])


if __name__ == '__main__':
    unittest.main()
