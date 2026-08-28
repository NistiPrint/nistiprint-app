"""Resolucao do vinculo de roteamento de uma conta.

Dois defeitos concretos que estes testes fixam:

1. A consulta filtrava por `ingest_origin_mode = 'marketplace_direct'`. Um
   vinculo em `erp_bling` registrado so em `erp_marketplace_links` ficava
   invisivel, a busca caia no cadastro legado e, sem linha la, o webhook virava
   `skipped_inactive_source` — descartado em silencio — em vez do
   `pending_erp_order` pretendido.

2. A linha devolvida nao trazia `channel_id`, e por isso 1.804 pedidos do
   Mercado Livre nasceram com `canal_venda_id` nulo enquanto o cadastro legado
   dizia canal 9.
"""
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    MarketplaceWebhookIngestService,
)


class _Supabase:
    """Devolve linhas por tabela, ignorando a ordem dos filtros encadeados."""

    def __init__(self, por_tabela):
        self.por_tabela = por_tabela
        self.tabelas_consultadas = []

    def table(self, nome):
        self.tabelas_consultadas.append(nome)
        linhas = self.por_tabela.get(nome, [])
        query = MagicMock()
        for metodo in ("select", "eq", "limit", "order"):
            getattr(query, metodo).return_value = query
        query.execute.return_value = MagicMock(data=linhas)
        return query


class FindDirectIngestLinkTest(unittest.TestCase):
    def setUp(self):
        self.service = MarketplaceWebhookIngestService()

    def _resolver(self, por_tabela):
        fake = _Supabase(por_tabela)
        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.supabase_db",
            fake,
        ):
            return self.service._find_direct_ingest_link(7091), fake

    def test_vinculo_erp_bling_e_devolvido_e_nao_ignorado(self):
        link, _ = self._resolver(
            {
                "erp_marketplace_links": [
                    {
                        "id": "abc",
                        "erp_integration_id": 3,
                        "marketplace_integration_id": 7091,
                        "process_webhooks": True,
                        "ingest_origin_mode": "erp_bling",
                        "erp_store_id": "205421972",
                        "channel_id": 9,
                    }
                ]
            }
        )
        self.assertIsNotNone(link)
        self.assertEqual(link["ingest_origin_mode"], "erp_bling")
        self.assertEqual(link["bling_integration_id"], 3)
        self.assertEqual(link["aggregator_store_id"], "205421972")

    def test_canal_vem_do_vinculo(self):
        link, fake = self._resolver(
            {
                "erp_marketplace_links": [
                    {
                        "id": "abc",
                        "erp_integration_id": 1,
                        "marketplace_integration_id": 7091,
                        "process_webhooks": True,
                        "ingest_origin_mode": "marketplace_direct",
                        "erp_store_id": "203753446",
                        "channel_id": 9,
                    }
                ]
            }
        )
        self.assertEqual(link["channel_id"], 9)
        self.assertNotIn("channel_connections", fake.tabelas_consultadas)

    def test_canal_cai_no_cadastro_legado_enquanto_o_backfill_nao_chega(self):
        link, fake = self._resolver(
            {
                "erp_marketplace_links": [
                    {
                        "id": "abc",
                        "erp_integration_id": 1,
                        "marketplace_integration_id": 7091,
                        "process_webhooks": True,
                        "ingest_origin_mode": "marketplace_direct",
                        "erp_store_id": "203753446",
                        "channel_id": None,
                    }
                ],
                "channel_connections": [{"channel_id": 9}],
            }
        )
        self.assertEqual(link["channel_id"], 9)
        self.assertIn("channel_connections", fake.tabelas_consultadas)

    def test_sem_vinculo_algum_devolve_none(self):
        link, _ = self._resolver({"erp_marketplace_links": [], "channel_connections": []})
        self.assertIsNone(link)

    def test_sem_integracao_nao_consulta_nada(self):
        fake = _Supabase({})
        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.supabase_db",
            fake,
        ):
            self.assertIsNone(self.service._find_direct_ingest_link(None))
        self.assertEqual(fake.tabelas_consultadas, [])
