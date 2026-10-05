import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import routes.integracao_canais as api
import routes.despacho as despacho
from nistiprint_shared.services import logistica_manutencao_service as svc


class LogisticsApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test')
        app.register_blueprint(api.integracao_canais_bp, url_prefix='/api/v2/integracao-canais')
        app.register_blueprint(despacho.despacho_bp, url_prefix='/api/v2/despacho')
        self.client = app.test_client()

    def login(self, admin=True):
        with self.client.session_transaction() as session:
            session['user_id'] = 7
            session['user_is_admin'] = admin

    def test_maintenance_requires_admin(self):
        url = '/api/v2/integracao-canais/logistica/modalidades'
        with patch.object(api.logistica, 'salvar_modalidade') as save:
            self.assertEqual(self.client.post(url, json={}).status_code, 401)
            self.login(False)
            self.assertEqual(self.client.post(url, json={}).status_code, 403)
        save.assert_not_called()

    def test_partial_edit_uses_transaction_and_actor(self):
        self.login()
        with patch.object(api.logistica, 'salvar_regra', return_value={'id': 12, 'ativo': False}) as save:
            res = self.client.put('/api/v2/integracao-canais/logistica/regras/12', json={'ativo': False})
        self.assertEqual(res.status_code, 200)
        save.assert_called_once_with({'ativo': False}, 12, '7')

    def test_malformed_json_is_client_error_without_saving(self):
        self.login()
        with patch.object(api.logistica, 'salvar_modalidade') as save:
            res = self.client.post('/api/v2/integracao-canais/logistica/modalidades',
                                   data='{invalid', content_type='application/json')
        self.assertEqual(res.status_code, 400)
        save.assert_not_called()

    def test_invalid_period_and_empty_exception_are_rejected(self):
        self.login()
        with patch.object(api.logistica, 'rpc_data') as rpc:
            res = self.client.get('/api/v2/integracao-canais/logistica/agenda?marketplace_integration_id=1&inicio=2026-10-01&fim=2026-12-01')
            self.assertEqual(res.status_code, 400)
            res = self.client.put('/api/v2/integracao-canais/logistica/regras/12/excecoes/2026-10-02', json=None)
            self.assertEqual(res.status_code, 400)
        rpc.assert_not_called()

    def test_no_collection_exception_and_restore_are_distinct(self):
        self.login()
        with patch.object(api.logistica, 'rpc_data', return_value={}) as rpc:
            data = {'janelas': [], 'motivo': 'Feriado'}
            res = self.client.put('/api/v2/integracao-canais/logistica/regras/12/excecoes/2026-10-02', json=data)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(rpc.call_args.args[1]['p_dados'], data)
            res = self.client.delete('/api/v2/integracao-canais/logistica/regras/12/excecoes/2026-10-02')
            self.assertEqual(res.status_code, 200)
            self.assertIsNone(rpc.call_args.args[1]['p_dados'])

    def test_conflicting_association_returns_409(self):
        self.login()
        error = RuntimeError('Existe associacao')
        error.code, error.message = '23505', 'Existe associacao'
        with patch.object(api.logistica, 'associar', side_effect=error):
            res = self.client.post('/api/v2/integracao-canais/logistica/canais/associar', json={'chave': 'x'})
        self.assertEqual(res.status_code, 409)

    def test_manual_sync_uses_configured_celery_client(self):
        self.login()
        from nistiprint_shared.services.celery_app import celery_app
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{'id': 1, 'module_id': 'mercadolivre'}]
        with patch.object(api, 'supabase_db', db), patch.object(celery_app, 'send_task', return_value=SimpleNamespace(id='operation-1')) as send:
            res = self.client.post('/api/v2/integracao-canais/logistica/sincronizar', json={'marketplace_integration_id': 1})
        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.get_json()['data']['operation_id'], 'operation-1')
        send.assert_called_once_with('nistiprint_shared.services.logistica_sync_service.sincronizar_agendas', args=[1])

    def test_alerts_include_published_demand_and_require_auth(self):
        with patch.object(despacho, 'get_current_user', return_value=None):
            self.assertEqual(self.client.get('/api/v2/despacho/alertas-logisticos').status_code, 401)
        q = MagicMock()
        q.select.return_value = q
        q.not_.is_.return_value = q
        q.not_.in_.return_value = q
        q.execute.return_value = SimpleNamespace(data=[{'id': 3, 'demanda_id': 'D3', 'logistica_divergencia': {}}])
        with patch.object(despacho, 'get_current_user', return_value={'id': 7}), \
             patch.object(despacho.supabase_db, 'table', return_value=q), \
             patch.object(svc, 'rpc_data', return_value=[{'pedido_id': 1, 'demanda_publicada': True}]):
            res = self.client.get('/api/v2/despacho/alertas-logisticos')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['data']['pedidos'][0]['demanda_publicada'])
        self.assertEqual(res.get_json()['data']['divergencias'][0]['id'], 3)
