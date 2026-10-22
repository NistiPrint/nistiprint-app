import unittest
from unittest.mock import MagicMock

from nistiprint_shared.services.catalogo_familia_service import CatalogoFamiliaService


class CatalogoFamiliaServiceTests(unittest.TestCase):
    def test_save_passes_version_and_explicit_inactivation_to_atomic_rpc(self):
        db = MagicMock()
        db.rpc.return_value.execute.return_value.data = {'catalogo_versao': 5}
        service = CatalogoFamiliaService(db)
        result = service.save(10, {
            'expected_version': 4,
            'eixos': [{'name': 'Cor', 'options': ['Azul'], 'position': 1}],
            'variacoes': [{'produto_id': 25, 'variation_values': {'Cor': 'Azul'}}],
            'inativar_ids': [26],
        }, 'user-1')
        self.assertEqual(result['catalogo_versao'], 5)
        args = db.rpc.call_args.args
        self.assertEqual(args[0], 'catalogo_salvar_familia')
        self.assertEqual(args[1]['p_expected_version'], 4)
        self.assertEqual(args[1]['p_eixos'], [{'name': 'Cor', 'options': ['Azul'], 'position': 1}])
        self.assertEqual(args[1]['p_inativar_ids'], [26])
        self.assertEqual(args[1]['p_usuario'], 'user-1')

    def test_legacy_variant_ids_are_translated_without_database_writes(self):
        rows = CatalogoFamiliaService._normalize_variants([
            {'id': '25', 'sku': 'SKU-AZ', 'variation_values': {'Cor': 'Azul'}},
            {'id': 'draft-1', 'sku': 'SKU-NEW'},
        ])
        self.assertEqual(rows[0]['produto_id'], 25)
        self.assertNotIn('id', rows[0])
        self.assertNotIn('produto_id', rows[1])
        self.assertEqual(rows[0]['variation_values'], {'Cor': 'Azul'})

    def test_missing_expected_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'expected_version'):
            CatalogoFamiliaService(MagicMock()).save(10, {'eixos': [], 'variacoes': []})


if __name__ == '__main__':
    unittest.main()
