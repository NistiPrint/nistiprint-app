import unittest
from unittest.mock import patch
from nistiprint_shared.services.product_service import ProductService


class ProductImportMetadataTests(unittest.TestCase):
    def payload(self, metadata=None):
        with patch('nistiprint_shared.services.product_service.supabase_db') as db:
            db.table.return_value.insert.return_value.execute.return_value.data=[{'id':10}]
            service=ProductService()
            values={'sku':'SKU','name':'Produto','status':'inativo'}
            if metadata is not None:values['import_metadata']=metadata
            service.create(values)
            return db.table.return_value.insert.call_args.args[0]

    def test_provenance_and_unknown_prices_are_in_initial_insert(self):
        metadata={'run_id':'run','key':'6:1:2'}
        data=self.payload(metadata)
        self.assertEqual(data['atributos']['importacao_catalogo'],metadata)
        self.assertIsNone(data['preco_custo'])
        self.assertIsNone(data['preco_venda'])
        self.assertIsNone(data['precificacao']['cost_price'])

    def test_ordinary_creation_keeps_legacy_defaults(self):
        self.assertEqual(self.payload()['preco_custo'],0)

    def test_incomplete_import_identity_is_rejected(self):
        with self.assertRaises(ValueError):self.payload({'run_id':'run'})
