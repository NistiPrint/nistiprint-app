"""Contagens e previa usam a mesma selecao; consultas nao crescem por card."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import routes.despacho as modulo


class TestLeiturasDespacho(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='local-test')
        app.register_blueprint(modulo.despacho_bp, url_prefix='/api/v2/despacho')
        self.client = app.test_client()

    def test_escopo_previa_acoes_compartilham_ids_sem_reler_arvore(self):
        banco = MagicMock()
        linhas = [
            {'titulo_anuncio': 'Agenda diária', 'sku_externo': 'AGD-AZ', 'variacao': 'Azul',
             'quantidade': 24, 'produto_id': 31, 'miolo': 'Azul', 'contabiliza_estoque': True,
             'pedidos_origem': [1]},
            {'titulo_anuncio': 'Agenda diária', 'sku_externo': 'AGD-RS', 'variacao': 'Rosa',
             'quantidade': 12, 'produto_id': 32, 'miolo': 'Rosa', 'contabiliza_estoque': True,
             'pedidos_origem': [1]},
        ]
        contexto = {'pedido_ids': [1], 'pedidos': [{'id': 1, 'marketplace_order_id': 'SH1',
                    'erp_integration_id': 9, 'erp_order_id': '77', 'erp_order_number': '88'}],
                    'pacotes': [], 'buckets': {'amanha': 1, 'depois': 15}, 'total_no': 16,
                    'contas': {'9': 'Bling'}}
        def rpc(nome, params):
            data = contexto if nome == 'despacho_escopo_contexto' else linhas
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))
        banco.rpc.side_effect = rpc
        with patch.object(modulo, 'get_current_user', return_value={'id': 1}), patch.object(modulo, 'supabase_db', banco):
            response = self.client.get('/api/v2/despacho/escopo?integration_id=6&modalidade_ids=1&horizonte=amanha&data=2026-10-05&incluir_previsao=1')
        data = response.get_json()['data']
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['total_no'], 16)
        self.assertEqual(data['previsao']['total_pedidos'], 1)
        self.assertEqual(len(data['previsao']['itens']), 2)
        self.assertEqual([item['descricao'] for item in data['previsao']['itens']], ['Agenda diária', 'Agenda diária'])
        self.assertEqual(sum(item['quantidade'] for item in data['previsao']['itens']), 36)
        self.assertEqual(data['acoes']['pedido_ids'], [1])
        self.assertEqual(data['acoes']['contas_erp'][0]['conta'], 'Bling')
        self.assertEqual([c.args[0] for c in banco.rpc.call_args_list],
                         ['despacho_escopo_contexto', 'despacho_consolidar_pedidos'])
        banco.table.assert_not_called()

    def test_escopo_vazio_preserva_contadores_de_outros_prazos(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data={
            'pedido_ids': [], 'pedidos': [], 'pacotes': [], 'buckets': {'amanha': 71},
            'total_no': 71, 'contas': {}})
        with patch.object(modulo, 'get_current_user', return_value={'id': 1}), patch.object(modulo, 'supabase_db', banco):
            data = self.client.get('/api/v2/despacho/escopo?horizonte=hoje').get_json()['data']
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['buckets'], {'amanha': 71})
        banco.rpc.assert_called_once()

    def test_torre_carrega_todos_metadados_em_uma_rpc(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data={
            'rows': [], 'timeline': [], 'catalogo': [], 'integracoes': [], 'composicao': [],
            'lotes': [], 'rascunhos': [], 'janelas': []})
        with patch.object(modulo, 'get_current_user', return_value={'id': 1}), patch.object(modulo, 'supabase_db', banco):
            response = self.client.get('/api/v2/despacho/arvore?data=2026-10-05')
        self.assertEqual(response.status_code, 200)
        banco.rpc.assert_called_once_with('despacho_arvore_contexto', {'p_data': '2026-10-05'})
        banco.table.assert_not_called()

    def test_torre_preserva_visao_anterior_sem_rpc_timeline(self):
        banco = MagicMock()
        base = {'integration_id': 6, 'marketplace_nome': 'Shopee',
                'modalidade_id': 1, 'modalidade_codigo': 'STANDARD', 'modalidade_nome': 'Comum',
                'tipo_prazo': 'FIXO', 'bucket_prazo': 'hoje', 'qtd_pedidos': 5,
                'qtd_itens': 5, 'corte_em': None, 'coleta_em': None,
                'prazo_final_em': None, 'compromisso_mais_proximo': None, 'coleta_grupo': None}
        contexto_antigo = {
            'rows': [dict(base, nivel=n) for n in range(5)],
            'catalogo': [{'id': 1, 'entrega_rapida': False}],
            'integracoes': [{'id': 6, 'module_id': 'shopee'}],
            'composicao': [], 'lotes': [], 'rascunhos': [], 'janelas': [],
        }

        def rpc(nome, _params):
            if nome == 'despacho_arvore_contexto':
                return SimpleNamespace(execute=lambda: SimpleNamespace(data=contexto_antigo))
            raise RuntimeError('function not installed')

        banco.rpc.side_effect = rpc
        with patch.object(modulo, 'get_current_user', return_value={'id': 1}), patch.object(modulo, 'supabase_db', banco):
            response = self.client.get('/api/v2/despacho/arvore?data=2026-10-05')

        self.assertEqual(response.status_code, 200)
        data = response.get_json()['data']
        self.assertFalse(data['linha_tempo_disponivel'])
        self.assertEqual(data['marketplaces'][0]['modalidades'][0]['qtd_pedidos'], 5)
        self.assertEqual(data['lotes_timeline'], [])

    def test_falha_real_nao_e_mascarada_pelo_fallback(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.side_effect = RuntimeError('database unavailable')
        with patch.object(modulo, 'get_current_user', return_value={'id': 1}), patch.object(modulo, 'supabase_db', banco):
            response = self.client.get('/api/v2/despacho/escopo')
        self.assertEqual(response.status_code, 500)
        banco.rpc.assert_called_once()

    def test_torre_conta_prazos_sem_somar_niveis_de_coleta(self):
        banco = MagicMock()
        base = {'integration_id': 6, 'marketplace_nome': 'Shopee',
                'modalidade_id': 1, 'modalidade_codigo': 'STANDARD', 'modalidade_nome': 'Comum',
                'tipo_prazo': 'FIXO', 'bucket_prazo': 'amanha', 'qtd_pedidos': 71,
                'qtd_itens': 80, 'corte_em': None, 'coleta_em': None,
                'prazo_final_em': None, 'compromisso_mais_proximo': None, 'coleta_grupo': None}
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data={
            'rows': [dict(base, nivel=n) for n in range(5)],
            'catalogo': [{'id': 1, 'entrega_rapida': False}],
            'integracoes': [{'id': 6, 'module_id': 'shopee'}],
            'composicao': [{'integration_id': 6, 'situacao_id': 2,
                            'situacao_nome': 'Em Andamento', 'qtd_pedidos': 71}],
            'timeline': [], 'lotes': [], 'rascunhos': [], 'janelas': []})
        with patch.object(modulo, 'get_current_user', return_value={'id': 1}), patch.object(modulo, 'supabase_db', banco):
            response = self.client.get('/api/v2/despacho/arvore?data=2026-10-05')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()['data']
        self.assertEqual(data['abas']['amanha'], 71)
        self.assertEqual(data['marketplaces'][0]['modalidades'][0]['por_aba']['amanha'], 71)
        banco.rpc.assert_called_once()
        banco.table.assert_not_called()

    def test_torre_expoe_lotes_timeline_por_data_limite(self):
        banco = MagicMock()
        base = {'integration_id': 6, 'marketplace_nome': 'Shopee',
                'modalidade_id': 1, 'modalidade_codigo': 'STANDARD', 'modalidade_nome': 'Comum',
                'tipo_prazo': 'FIXO', 'bucket_prazo': 'hoje', 'qtd_pedidos': 50,
                'qtd_itens': 50, 'corte_em': None, 'coleta_em': None,
                'prazo_final_em': None, 'compromisso_mais_proximo': None, 'coleta_grupo': None}
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data={
            'rows': [dict(base, nivel=n) for n in range(5)],
            'timeline': [{
                'integration_id': 6, 'marketplace_nome': 'Shopee', 'modalidade_id': 1,
                'modalidade_codigo': 'STANDARD', 'modalidade_nome': 'Comum',
                'tipo_prazo': 'FIXO', 'entrega_rapida': False,
                'data_limite_dia': '2026-10-07', 'bucket_prazo': 'hoje',
                'qtd_pedidos': 50, 'proxima_saida_em': '2026-10-07T15:00:00-03:00',
                'saida_apos_prazo': False,
            }, {
                'integration_id': 6, 'marketplace_nome': 'Shopee', 'modalidade_id': 2,
                'modalidade_codigo': 'PICKUP', 'modalidade_nome': 'Retirada',
                'tipo_prazo': 'FIXO', 'entrega_rapida': False,
                'data_limite_dia': '2026-10-07', 'bucket_prazo': 'hoje',
                'qtd_pedidos': 10, 'proxima_saida_em': '2026-10-07T15:00:00-03:00',
                'saida_apos_prazo': False,
            }],
            'catalogo': [{'id': 1, 'entrega_rapida': False}],
            'integracoes': [{'id': 6, 'module_id': 'shopee'}],
            'composicao': [],
            'lotes': [
                {'integration_id': 6, 'modalidade_id': 1, 'lote_chave': 'shared',
                 'modalidade_ids': [1, 2], 'lote_nome': 'Comum + Retirada', 'entrega_rapida': False},
                {'integration_id': 6, 'modalidade_id': 2, 'lote_chave': 'shared',
                 'modalidade_ids': [1, 2], 'lote_nome': 'Comum + Retirada', 'entrega_rapida': False},
            ],
            'rascunhos': [], 'janelas': [],
        })
        with patch.object(modulo, 'get_current_user', return_value={'id': 1}), patch.object(modulo, 'supabase_db', banco):
            response = self.client.get('/api/v2/despacho/arvore?data=2026-10-07')
        self.assertEqual(response.status_code, 200)
        lote = response.get_json()['data']['lotes_timeline'][0]
        self.assertEqual(lote['qtd_pedidos'], 60)
        self.assertEqual(lote['data_limite_dia'], '2026-10-07')
        self.assertEqual(lote['modalidade_ids'], [1, 2])
        self.assertEqual(lote['proxima_saida_em'], '2026-10-07T15:00:00-03:00')

    def test_data_operacional_independe_de_utc(self):
        self.assertEqual(modulo._bucket_operacional('2026-10-07T02:59:59Z', '2026-10-05'), 'amanha')
        self.assertEqual(modulo._bucket_operacional(None, '2026-10-05', '2026-10-06T03:00:00Z'), 'amanha')
        self.assertEqual(modulo._bucket_operacional(None, '2026-10-05'), 'sem_prazo')

    def test_autenticacao_antes_de_qualquer_consulta(self):
        banco = MagicMock()
        with patch.object(modulo, 'get_current_user', return_value=None), patch.object(modulo, 'supabase_db', banco):
            for endpoint in ('arvore', 'escopo'):
                self.assertEqual(self.client.get('/api/v2/despacho/' + endpoint).status_code, 401)
        banco.rpc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
