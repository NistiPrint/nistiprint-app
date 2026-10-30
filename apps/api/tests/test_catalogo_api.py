import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from routes import catalogo_api


class CatalogApiTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(catalogo_api.catalogo_bp)
        self.client = app.test_client()

    def test_relationship_filter_is_forwarded_with_account_and_product(self):
        with patch.object(catalogo_api, 'require_request_permission', return_value=None), patch.object(catalogo_api, 'AnuncioService') as service:
            service.return_value.list.return_value = {'rows': [], 'total': 0}
            result = self.client.get('/api/v2/anuncios?relationship=review&integration_id=6&produto_id=10')
        self.assertEqual(result.status_code, 200)
        args = service.return_value.list.call_args.kwargs
        self.assertEqual(args['relationship'], 'review')
        self.assertEqual(args['integration_id'], 6)
        self.assertEqual(args['produto_id'], 10)

    def test_missing_edit_permission_blocks_family_write(self):
        with patch.object(catalogo_api,'require_request_permission',return_value=('denied',403)),patch.object(catalogo_api,'CatalogoFamiliaService') as service:
            result = self.client.put('/api/v2/produtos/1/familia',json={})
        self.assertEqual(result.status_code,403)
        service.assert_not_called()

    def test_version_conflict_is_409(self):
        class Conflict(Exception):
            code = '40001'
        with patch.object(catalogo_api,'require_request_permission',return_value=None),patch.object(catalogo_api,'get_current_user',return_value={'id':1}),patch.object(catalogo_api,'CatalogoFamiliaService') as service:
            service.return_value.save.side_effect = Conflict()
            result = self.client.put('/api/v2/produtos/1/familia',json={'expected_version':1})
        self.assertEqual(result.status_code,409)

    def test_link_rejects_unit_from_another_account(self):
        with patch.object(catalogo_api,'require_request_permission',return_value=None),patch.object(catalogo_api,'supabase_db') as db:
            db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data=[{'id':1,'integration_id':7}]
            result = self.client.put('/api/v2/anuncios/unidades/1/vinculo',json={
                'integration_id':6,'expected_version':1,'produto_id':10,'motivo':'Revisão'})
        self.assertEqual(result.status_code,404)
        db.rpc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
