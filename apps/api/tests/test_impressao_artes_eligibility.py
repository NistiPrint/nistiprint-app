"""Artwork links follow the printable component, not its assembled parent."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402

with patch.object(supabase_db, 'table', return_value=MagicMock()):
    import routes.impressao_capas as impressao_capas  # noqa: E402
from nistiprint_shared.services.category_service import category_service  # noqa: E402


class TestArtworkEligibility(unittest.TestCase):
    def test_bom_exposes_only_printable_component_as_artwork_candidate(self):
        bom = {
            1: [SimpleNamespace(componente_id=2, quantidade=1)],
            2: [SimpleNamespace(componente_id=3, quantidade=1)],
            3: [],
        }
        products = {
            '2': {'nome': 'Capa pronta', 'sku': 'PRONTA', 'categoria_id': 3},
            '3': {'nome': 'Capa impressa', 'sku': 'IMPRESSA', 'categoria_id': 10},
        }
        with (
            patch.object(impressao_capas.bom_service, 'get_bom_for_produto', side_effect=lambda id: bom[id]),
            patch.object(impressao_capas.product_service, 'get_by_id', side_effect=lambda id: products[id]),
            patch.object(category_service, 'get_by_id', side_effect=lambda id: {'permite_arte': id == '10'}),
        ):
            candidates = impressao_capas._bom_candidates(1)

        self.assertFalse(candidates[2]['permite_arte'])
        self.assertIsNone(candidates[2]['papel_sugerido'])
        self.assertTrue(candidates[3]['permite_arte'])
        self.assertEqual(candidates[3]['papel_sugerido'], 'capa')

    def test_api_rejects_artwork_link_to_assembled_component(self):
        app = Flask(__name__)
        with (
            app.test_request_context(json={'nome': 'Capa', 'componentes': [{'componente_id': 2, 'papel': 'capa'}]}),
            patch.object(impressao_capas.product_service, 'get_by_id', return_value={'tipo_material': 'produto_acabado'}),
            patch.object(impressao_capas, '_bom_candidates', return_value={2: {'permite_arte': False}}),
            patch.object(impressao_capas.supabase_db, 'rpc') as rpc,
        ):
            response, status = impressao_capas._save_artwork(1)

        self.assertEqual(status, 400)
        self.assertIn('categoria que permite arte', response.get_json()['error'])
        rpc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
