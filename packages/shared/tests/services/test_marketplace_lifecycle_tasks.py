import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import marketplace_lifecycle_tasks as tasks


class TestMarketplaceLifecycleTasks(unittest.TestCase):
    def test_process_pending_effects_calls_transactional_rpc(self):
        table = MagicMock()
        table.select.return_value = table
        table.eq.return_value = table
        table.order.return_value = table
        table.limit.return_value = table
        table.execute.return_value.data = [{'id': 10}]
        rpc_query = MagicMock()
        rpc_query.execute.return_value.data = {
            'effect_id': 10,
            'status': 'processed',
            'alerts': 1,
        }

        with patch.object(tasks.supabase_db, 'table', return_value=table), \
             patch.object(tasks.supabase_db, 'rpc', return_value=rpc_query) as rpc:
            result = tasks.process_pending_effects()

        self.assertEqual(result['processed'], 1)
        self.assertEqual(result['failed'], 0)
        rpc.assert_called_once_with(
            'process_marketplace_order_effect',
            {'p_effect_id': 10},
        )


class TestReconcileMarketplaceLifecycleQuery(unittest.TestCase):
    """A consulta do backfill: `days` precisa filtrar e `offset` precisa ser keyset."""

    def _query_mock(self, rows):
        query = MagicMock()
        for metodo in ('select', 'in_', 'gte', 'gt', 'order', 'limit'):
            getattr(query, metodo).return_value = query
        query.execute.return_value.data = rows
        return query

    def test_days_filtra_por_data_de_venda(self):
        query = self._query_mock([])
        with patch.object(tasks.supabase_db, 'table', return_value=query):
            tasks.reconcile_marketplace_lifecycle(days=90, limit=100)

        query.gte.assert_called_once()
        self.assertEqual(query.gte.call_args.args[0], 'data_venda')

    def test_days_zero_nao_filtra(self):
        query = self._query_mock([])
        with patch.object(tasks.supabase_db, 'table', return_value=query):
            tasks.reconcile_marketplace_lifecycle(days=0, limit=100)

        query.gte.assert_not_called()

    def test_offset_e_keyset_por_id_nao_deslocamento(self):
        query = self._query_mock([])
        with patch.object(tasks.supabase_db, 'table', return_value=query):
            tasks.reconcile_marketplace_lifecycle(offset=5000, limit=100)

        query.gt.assert_called_once_with('id', 5000)
        query.limit.assert_called_once_with(100)

    def test_next_offset_e_o_ultimo_id_do_lote(self):
        """Deslocamento pularia linhas: o conjunto encolhe a cada correcao."""
        rows = [
            {
                'id': 4001,
                'numero_pedido': '1',
                'marketplace_module_id': 'mercadolivre',
                'marketplace_order_id': '2000',
                'marketplace_integration_id': 7091,
                'situacao_pedido_id': 2,
            },
        ]
        query = self._query_mock(rows)
        with (
            patch.object(tasks.supabase_db, 'table', return_value=query),
            patch.object(
                tasks, 'MarketplaceWebhookIngestService', create=True,
            ),
        ):
            resultado = tasks.reconcile_marketplace_lifecycle(limit=100)

        self.assertEqual(resultado['next_offset'], 4001)
        self.assertFalse(resultado['has_more'])


class TestPrefetchShopeeEmLote(unittest.TestCase):
    """Cem pedidos Shopee viravam cem chamadas; a API aceita 50 por vez."""

    def _rows(self, quantidade, integration_id=20):
        return [
            {
                'id': 1000 + i,
                'marketplace_module_id': 'shopee',
                'marketplace_order_id': f'25080{i:04d}',
                'marketplace_integration_id': integration_id,
            }
            for i in range(quantidade)
        ]

    def test_agrupa_por_integracao_em_uma_chamada(self):
        rows = self._rows(40)
        ingest = MagicMock()
        ingest._hydrate_shopee_integration.side_effect = lambda i: i
        integracoes = {20: {'id': 20, 'module_id': 'shopee'}}

        with patch(
            'nistiprint_shared.services.platform_drivers.shopee.get_order_details_batch',
            return_value={r['marketplace_order_id']: {'external_id': r['marketplace_order_id']}
                          for r in rows},
        ) as batch:
            detalhes = tasks._prefetch_detalhes_shopee(rows, integracoes, ingest)

        batch.assert_called_once()
        self.assertEqual(len(batch.call_args.args[1]), 40)
        self.assertEqual(len(detalhes), 40)

    def test_meli_fica_fora_do_prefetch(self):
        """Detalhe do ML exige envio e SLA, que nao tem endpoint em lote."""
        rows = self._rows(2) + [{
            'id': 9, 'marketplace_module_id': 'mercadolivre',
            'marketplace_order_id': '2000', 'marketplace_integration_id': 20,
        }]
        ingest = MagicMock()
        ingest._hydrate_shopee_integration.side_effect = lambda i: i

        with patch(
            'nistiprint_shared.services.platform_drivers.shopee.get_order_details_batch',
            return_value={},
        ) as batch:
            tasks._prefetch_detalhes_shopee(rows, {20: {'id': 20}}, ingest)

        self.assertEqual(batch.call_args.args[1], ['250800000', '250800001'])

    def test_falha_do_lote_vira_erro_por_pedido(self):
        """Um lote que falha nao pode deixar pedido sem resposta nenhuma."""
        rows = self._rows(3)
        ingest = MagicMock()
        ingest._hydrate_shopee_integration.side_effect = lambda i: i

        with patch(
            'nistiprint_shared.services.platform_drivers.shopee.get_order_details_batch',
            side_effect=RuntimeError('429 rate limit'),
        ):
            detalhes = tasks._prefetch_detalhes_shopee(rows, {20: {'id': 20}}, ingest)

        self.assertEqual(len(detalhes), 3)
        for row in rows:
            self.assertIn('429', detalhes[row['marketplace_order_id']]['error'])

    def test_integracoes_carregadas_de_uma_vez(self):
        rows = self._rows(5, integration_id=20) + self._rows(5, integration_id=21)
        query = MagicMock()
        query.select.return_value = query
        query.in_.return_value = query
        query.execute.return_value.data = [{'id': 20}, {'id': 21}]

        with patch.object(tasks.supabase_db, 'table', return_value=query) as table:
            integracoes = tasks._integracoes_do_lote(rows)

        table.assert_called_once_with('installed_integrations')
        self.assertEqual(sorted(integracoes), [20, 21])
        self.assertEqual(sorted(query.in_.call_args.args[1]), [20, 21])


class TestTravaDaCadeiaDeBackfill(unittest.TestCase):
    """A task se auto-encadeia E esta no beat: sem trava, as cadeias empilham."""

    def _sem_trabalho(self):
        return {
            'status': 'success', 'dry_run': True, 'days': 90, 'compared': 0,
            'failed': [], 'next_offset': 0, 'has_more': False,
            'projection_enabled': False,
        }

    def test_novo_disparo_e_ignorado_com_cadeia_viva(self):
        with (
            patch.object(tasks, '_adquirir_trava_da_cadeia', return_value=None),
            patch.object(tasks, 'reconcile_marketplace_lifecycle') as backfill,
        ):
            resultado = tasks.reconcile_marketplace_lifecycle_task.run()

        backfill.assert_not_called()
        self.assertEqual(resultado['status'], 'skipped')
        self.assertEqual(resultado['reason'], 'chain_already_running')

    def test_lote_encadeado_nao_readquire_a_trava(self):
        """Os lotes seguintes carregam o token: readquirir seria auto-bloqueio."""
        with (
            patch.object(tasks, '_adquirir_trava_da_cadeia') as adquirir,
            patch.object(tasks, '_liberar_trava_da_cadeia') as liberar,
            patch.object(
                tasks, 'reconcile_marketplace_lifecycle',
                return_value=self._sem_trabalho(),
            ),
        ):
            tasks.reconcile_marketplace_lifecycle_task.run(chain_token='tok-1')

        adquirir.assert_not_called()
        liberar.assert_called_once_with('tok-1')

    def test_fim_da_cadeia_libera_a_trava(self):
        with (
            patch.object(tasks, '_adquirir_trava_da_cadeia', return_value='tok-2'),
            patch.object(tasks, '_liberar_trava_da_cadeia') as liberar,
            patch.object(
                tasks, 'reconcile_marketplace_lifecycle',
                return_value=self._sem_trabalho(),
            ),
        ):
            tasks.reconcile_marketplace_lifecycle_task.run()

        liberar.assert_called_once_with('tok-2')

    def test_proximo_lote_herda_o_token_e_renova_a_trava(self):
        resultado_parcial = {**self._sem_trabalho(), 'has_more': True,
                             'next_offset': 4001}
        with (
            patch.object(tasks, '_adquirir_trava_da_cadeia', return_value='tok-3'),
            patch.object(tasks, '_renovar_trava_da_cadeia') as renovar,
            patch.object(tasks, '_liberar_trava_da_cadeia') as liberar,
            patch.object(
                tasks, 'reconcile_marketplace_lifecycle',
                return_value=resultado_parcial,
            ),
            patch.object(
                tasks.reconcile_marketplace_lifecycle_task, 'apply_async',
            ) as apply_async,
        ):
            tasks.reconcile_marketplace_lifecycle_task.run()

        renovar.assert_called_once_with('tok-3')
        liberar.assert_not_called()
        kwargs = apply_async.call_args.kwargs['kwargs']
        self.assertEqual(kwargs['chain_token'], 'tok-3')
        self.assertEqual(kwargs['offset'], 4001)

    def test_falha_no_lote_libera_a_trava(self):
        """Cadeia morta sem liberar travaria o backfill ate o TTL expirar."""
        with (
            patch.object(tasks, '_adquirir_trava_da_cadeia', return_value='tok-4'),
            patch.object(tasks, '_liberar_trava_da_cadeia') as liberar,
            patch.object(
                tasks, 'reconcile_marketplace_lifecycle',
                side_effect=RuntimeError('boom'),
            ),
        ):
            with self.assertRaises(RuntimeError):
                tasks.reconcile_marketplace_lifecycle_task.run()

        liberar.assert_called_once_with('tok-4')


if __name__ == '__main__':
    unittest.main()
