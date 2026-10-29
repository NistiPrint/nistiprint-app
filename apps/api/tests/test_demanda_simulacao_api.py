"""Rotas de simulação não passam pelo serviço operacional de demandas."""

import sys
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.demanda_simulacao_api as module  # noqa: E402
import routes.despacho as despacho  # noqa: E402


class SimulationApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test')
        app.register_blueprint(module.simulacao_bp)
        self.client = app.test_client()
        self.ident = str(uuid4())
        self.state = module.create_state(
            [{'produto': 'Manual', 'sku': 'M', 'quantidade': 2}],
            [{'id': 7, 'pedido_id': 7}], {})
        self.row = {'id': self.ident, 'state': self.state, 'version': 1}

    def _auth(self):
        return (patch.object(module, '_active_session_user', return_value={'id': 4}),
                patch.object(module, 'user_has_permission', return_value=True))

    def test_stale_action_has_no_write(self):
        db = MagicMock()
        with self._auth()[0], self._auth()[1], patch.object(module, 'supabase_db', db), patch.object(module, '_row', return_value=self.row):
            db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
            response = self.client.post(f'/api/v2/demanda-simulacoes/{self.ident}/acoes', json={
                'version': 2, 'operation_id': str(uuid4()), 'action': 'publicar', 'payload': {},
            })
        self.assertEqual(response.status_code, 409)
        db.rpc.assert_not_called()

    def test_collect_requires_existing_demand_action_permission(self):
        db = MagicMock()
        with self._auth()[0], self._auth()[1], \
             patch.object(module, 'user_has_demand_permission', return_value=False), \
             patch.object(module, 'supabase_db', db):
            response = self.client.post(f'/api/v2/demanda-simulacoes/{self.ident}/acoes', json={
                'version': 1, 'operation_id': str(uuid4()),
                'action': 'coletar', 'payload': {'quantidade': 1},
            })
        self.assertEqual(response.status_code, 403)
        db.rpc.assert_not_called()

    def test_action_calls_only_isolated_rpc(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
        next_row = {**self.row, 'version': 2, 'state': module.transition(self.state, 'publicar', {})}
        db.rpc.return_value.execute.return_value = SimpleNamespace(data=next_row)
        with self._auth()[0], self._auth()[1], patch.object(module, 'supabase_db', db), patch.object(module, '_row', return_value=self.row):
            response = self.client.post(f'/api/v2/demanda-simulacoes/{self.ident}/acoes', json={
                'version': 1, 'operation_id': str(uuid4()), 'action': 'publicar', 'payload': {},
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.rpc.call_args.args[0], 'demanda_simulacao_alterar')
        self.assertEqual(response.get_json()['demanda']['status'], 'AGUARDANDO')

    def test_creation_copies_manual_line_and_calls_only_simulation_rpcs(self):
        db = MagicMock()
        db.table.return_value.select.return_value.in_.return_value.execute.return_value = SimpleNamespace(
            data=[{'id': 7, 'numero_pedido': 'P-7', 'cliente_nome': 'Cliente'}])
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
        db.rpc.side_effect = lambda name, params: SimpleNamespace(execute=lambda: SimpleNamespace(
            data='fp' if name == 'demanda_simulacao_fingerprint' else self.row))
        preview = {'previsao_versao': 'v1', 'itens': [{'linha_chave': 'original'}]}
        with self._auth()[0], self._auth()[1], patch.object(module, 'supabase_db', db), \
             patch.object(despacho, '_pedido_ids_do_lote', return_value=([7], 'scope')), \
             patch.object(despacho, '_previsao_do_lote', return_value=preview):
            response = self.client.post('/api/v2/demanda-simulacoes', json={
                'operation_id': str(uuid4()),
                'previsao_versao': 'v1', 'linhas': [
                    {'linha_chave': 'original', 'produto': 'Original', 'quantidade': 1},
                    {'produto': 'Manual', 'sku': 'M', 'quantidade': 2},
                ],
            })
        self.assertEqual(response.status_code, 201)
        names = [call.args[0] for call in db.rpc.call_args_list]
        self.assertEqual(names, ['demanda_simulacao_fingerprint', 'demanda_simulacao_fingerprint', 'demanda_simulacao_criar'])
        saved_state = db.rpc.call_args_list[-1].args[1]['p_state']
        self.assertEqual(saved_state['itens'][1]['item_descricao'], 'Manual')

    def test_creation_resolves_miolo_sku_before_saving_state(self):
        db = MagicMock()
        db.table.return_value.select.return_value.in_.return_value.execute.return_value = SimpleNamespace(
            data=[{'id': 7, 'numero_pedido': 'P-7', 'cliente_nome': 'Cliente'}])
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[
            {'id': 88, 'nome': 'Miolo VACMNO', 'sku': 'MIOLO-VACMNO'},
        ])
        db.rpc.side_effect = lambda name, params: SimpleNamespace(execute=lambda: SimpleNamespace(
            data='fp' if name == 'demanda_simulacao_fingerprint' else self.row))
        preview = {'previsao_versao': 'v1', 'itens': [{'linha_chave': 'original'}]}
        with self._auth()[0], self._auth()[1], patch.object(module, 'supabase_db', db), \
             patch.object(module, '_categoria_miolos_id', return_value=6), \
             patch.object(despacho, '_pedido_ids_do_lote', return_value=([7], 'scope')), \
             patch.object(despacho, '_previsao_do_lote', return_value=preview):
            response = self.client.post('/api/v2/demanda-simulacoes', json={
                'operation_id': str(uuid4()), 'previsao_versao': 'v1',
                'linhas': [{'linha_chave': 'original', 'produto': 'Caderneta',
                            'sku': 'VACMNO_MNV2_BVB', 'miolo': 'VACMNO', 'quantidade': 1}],
            })

        self.assertEqual(response.status_code, 201)
        saved_state = db.rpc.call_args_list[-1].args[1]['p_state']
        self.assertEqual(saved_state['itens'][0]['id_produto_miolo'], 88)
        self.assertEqual(saved_state['itens'][0]['miolo_nome'], 'VACMNO')

    def test_miolo_match_requires_one_unique_product_and_preserves_existing_id(self):
        products = [
            {'id': 88, 'nome': 'Miolo VACMNO', 'sku': 'MIOLO-VACMNO'},
            {'id': 89, 'nome': 'Miolo VACMNO alternativo', 'sku': 'OUTRO'},
        ]
        self.assertEqual(module._produto_miolo_id_unico('VACMNO', products), 88)
        self.assertIsNone(module._produto_miolo_id_unico('SEM-CADASTRO', products))
        self.assertIsNone(module._produto_miolo_id_unico('DUPLICADO', [
            {'id': 1, 'nome': 'Miolo Duplicado', 'sku': 'MIOLO-DUPLICADO'},
            {'id': 2, 'nome': 'Miolo Duplicado', 'sku': 'OUTRO'},
        ]))
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=products)
        with patch.object(module, 'supabase_db', db), \
             patch.object(module, '_categoria_miolos_id', return_value=6):
            linhas = module._resolver_miolos_simulacao([
                {'miolo': 'VACMNO', 'id_produto_miolo': 777},
                {'miolo_nome': 'SEM-CADASTRO'},
            ])
        self.assertEqual(linhas[0]['id_produto_miolo'], 777)
        self.assertNotIn('id_produto_miolo', linhas[1])
        self.assertEqual(linhas[1]['miolo'], 'SEM-CADASTRO')

    def test_creation_rejects_stale_preview_without_write(self):
        db = MagicMock()
        db.rpc.return_value.execute.return_value = SimpleNamespace(data='fp')
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
        with self._auth()[0], self._auth()[1], patch.object(module, 'supabase_db', db), \
             patch.object(despacho, '_pedido_ids_do_lote', return_value=([7], 'scope')), \
             patch.object(despacho, '_previsao_do_lote', return_value={'previsao_versao': 'current'}):
            response = self.client.post('/api/v2/demanda-simulacoes', json={
                'operation_id': str(uuid4()),
                'previsao_versao': 'stale', 'linhas': [{'quantidade': 1}],
            })
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('demanda_simulacao_criar', [call.args[0] for call in db.rpc.call_args_list])

    def test_creation_retry_returns_existing_scenario(self):
        db = MagicMock()
        body = {'operation_id': str(uuid4()), 'previsao_versao': 'v1',
                'linhas': [{'produto': 'Manual', 'quantidade': 2}]}
        digest = hashlib.sha256(json.dumps(
            {key: value for key, value in body.items() if key != 'operation_id'},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{'simulacao_id': self.ident, 'request_hash': digest}])
        with self._auth()[0], self._auth()[1], patch.object(module, 'supabase_db', db), \
             patch.object(module, '_row', return_value=self.row):
            response = self.client.post('/api/v2/demanda-simulacoes', json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['demanda']['id'], self.ident)
        db.rpc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
