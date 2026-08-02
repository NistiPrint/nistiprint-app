import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import bling_order_processing_service as service


class TestBlingOrderProcessingService(unittest.TestCase):
    def test_materialize_marketplace_direct_order_marks_personalized_flags(self):
        detalhe = {
            "id": 987,
            "numero": "466320",
            "numeroLoja": "260618E2UXVM97",
            "loja": {"id": "204047801"},
            "contato": {"nome": "Sandro Gomes"},
            "situacao": {"id": 2},
            "itens": [
                {
                    "id": 1,
                    "descricao": "Caderneta de Vacinacao Personalizado C/ Nome",
                    "quantidade": 1,
                    "valor": 10,
                }
            ],
        }

        fake_client = MagicMock()
        fake_client.get_order_numbers_by_store_numbers.return_value = [{"id": 987, "numero": "466320"}]

        with patch("nistiprint_shared.services.bling.bling_client.BlingClient.create_client_for_integration_id", return_value=fake_client):
            with patch.object(service, "_fetch_bling_order_detail", return_value=detalhe):
                with patch.object(service, "_upsert_pedido_bling", return_value=321):
                    with patch.object(service, "_extract_bling_loja_id", return_value="204047801"):
                        with patch.object(service, "_resolve_canal_venda_id", return_value=27):
                            with patch.object(service, "_classify_fulfillment", return_value=SimpleNamespace(is_fulfillment=False, modalidade="STANDARD")):
                                with patch.object(service, "_classify_flex", return_value=SimpleNamespace(is_flex=False, modalidade="STANDARD")):
                                    with patch.object(service, "_upsert_pedido_master", return_value=26893):
                                        with patch.object(service, "_detect_and_mark_personalized") as detect_mock:
                                            result = service.materialize_marketplace_direct_order(
                                                source="shopee",
                                                external_order_id="260618E2UXVM97",
                                                marketplace_inst={"id": 12, "plataforma_slug": "shopee"},
                                                marketplace_detail={"buyer_username": "bruna.karoline_gomes"},
                                                marketplace_mirror_id=55,
                                                bling_integration_id=99,
                                                bling_loja_id="204047801",
                                            )

        self.assertEqual(result["status"], "success")
        detect_mock.assert_called_once_with(detalhe, 26893)

    def test_materialize_marketplace_direct_order_requires_bling_number(self):
        fake_client = MagicMock()
        fake_client.get_order_numbers_by_store_numbers.return_value = [{"id": 987, "numero": None}]

        with patch("nistiprint_shared.services.bling.bling_client.BlingClient.create_client_for_integration_id", return_value=fake_client):
            result = service.materialize_marketplace_direct_order(
                source="shopee",
                external_order_id="260618E2UXVM97",
                marketplace_inst={"id": 12, "plataforma_slug": "shopee"},
                marketplace_detail={"buyer_username": "bruna.karoline_gomes"},
                marketplace_mirror_id=55,
                bling_integration_id=99,
                bling_loja_id="204047801",
            )

        self.assertEqual(result, {"status": "error", "reason": "bling_order_incomplete"})


    def test_upsert_master_uses_canonical_marketplace_identity(self):
        payload = {
            "id": 987, "numero": "466320", "numeroLoja": "SN123",
            "loja": {"id": "204047801"}, "situacao": {"id": 2},
            "contato": {"nome": "Maria"}, "itens": [], "total": 10,
        }
        with patch.object(service, "_resolve_situacao_interna", return_value=4), \
             patch.object(service.logistica_coleta_service, "calcular_data_coleta", return_value={}), \
             patch.object(service.canonical_order_repository, "resolve_module_id", return_value="shopee"), \
             patch.object(service.canonical_order_repository, "resolve_erp_marketplace_link", return_value=None), \
             patch.object(service.canonical_order_repository, "upsert", return_value=77) as upsert, \
             patch.object(service, "_upsert_itens_pedido"):
            pedido_id = service._upsert_pedido_master(
                payload, pedido_bling_id=10, pedido_shopee_id=20,
                bling_integration_id=99, marketplace_integration_id=12,
                canal_venda_id=22, is_flex=False, modalidade="STANDARD",
                shopee_data={"buyer_username": "maria"},
            )

        self.assertEqual(pedido_id, 77)
        canonical_order = upsert.call_args.args[0]
        self.assertEqual(canonical_order["marketplace_module_id"], "shopee")
        self.assertEqual(canonical_order["marketplace_order_id"], "SN123")
        self.assertEqual(canonical_order["erp_order_id"], 987)

    def _upsert_master_with_link(self, link, order_exists):
        """Executa _upsert_pedido_master com um vinculo ERP x marketplace dado."""
        payload = {
            "id": 987, "numero": "466320", "numeroLoja": "SN123",
            "loja": {"id": "204047801"}, "situacao": {"id": 2},
            "contato": {"nome": "Maria"}, "itens": [], "total": 10,
        }
        with patch.object(service, "_resolve_situacao_interna", return_value=4), \
             patch.object(service.logistica_coleta_service, "calcular_data_coleta", return_value={}), \
             patch.object(service.canonical_order_repository, "resolve_module_id", return_value="shopee"), \
             patch.object(service.canonical_order_repository, "resolve_erp_marketplace_link", return_value=link), \
             patch.object(service.canonical_order_repository, "order_exists", return_value=order_exists), \
             patch.object(service.canonical_order_repository, "upsert", return_value=77) as upsert, \
             patch.object(service, "_upsert_itens_pedido"):
            service._upsert_pedido_master(
                payload, pedido_bling_id=10, pedido_shopee_id=20,
                bling_integration_id=99, marketplace_integration_id=12,
                canal_venda_id=22, is_flex=False, modalidade="STANDARD",
                shopee_data={"buyer_username": "maria"},
            )
        return upsert.call_args.args[0]

    def test_bling_does_not_overwrite_status_of_direct_marketplace_order(self):
        # Onde o marketplace integra direto, ele dita o ciclo de vida. O Bling
        # segue gravando identidade e fatos de ERP; so a projecao e suprimida.
        order = self._upsert_master_with_link(
            {"marketplace_module_id": "shopee", "ingest_origin_mode": "marketplace_direct"},
            order_exists=True,
        )
        # O payload enviado ao RPC filtra chaves nulas, entao a ausencia da
        # chave e o que faz o COALESCE preservar a situacao vigente.
        self.assertNotIn("situacao_pedido_id", order)
        self.assertEqual(order["erp_order_id"], 987)
        self.assertEqual(order["status_original"], "2")

    def test_bling_projects_when_it_sees_the_order_first(self):
        # Sem pedido materializado, projetar e melhor que deixar sem situacao.
        order = self._upsert_master_with_link(
            {"marketplace_module_id": "shopee", "ingest_origin_mode": "marketplace_direct"},
            order_exists=False,
        )
        self.assertEqual(order["situacao_pedido_id"], 4)

    def test_bling_remains_authoritative_without_direct_integration(self):
        order = self._upsert_master_with_link(
            {"marketplace_module_id": "shopee", "ingest_origin_mode": "erp_bling"},
            order_exists=True,
        )
        self.assertEqual(order["situacao_pedido_id"], 4)

    def test_missing_link_defaults_to_erp_authority(self):
        order = self._upsert_master_with_link(None, order_exists=True)
        self.assertEqual(order["situacao_pedido_id"], 4)

    def test_upsert_master_defers_order_without_marketplace_identity(self):
        payload = {
            "id": 987, "numero": "466320", "numeroLoja": None,
            "loja": {"id": "204047801"}, "situacao": {"id": 2},
            "contato": {}, "itens": [],
        }
        with patch.object(service, "_resolve_situacao_interna", return_value=4), \
             patch.object(service.canonical_order_repository, "resolve_module_id", return_value=None), \
             patch.object(service.canonical_order_repository, "resolve_erp_marketplace_link", return_value=None), \
             patch.object(service.canonical_order_repository, "defer_unresolved_erp_order") as defer:
            with self.assertRaises(service.OrderIdentityUnresolvedError):
                service._upsert_pedido_master(
                    payload, pedido_bling_id=10, pedido_shopee_id=None,
                    bling_integration_id=99, marketplace_integration_id=None,
                    canal_venda_id=None, is_flex=False, modalidade="STANDARD",
                )
        defer.assert_called_once()


    def test_reference_only_webhook_enriches_existing_marketplace_order(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{
            "id": 77, "erp_integration_id": None, "erp_store_id": None,
            "erp_order_id": None, "erp_order_number": None,
            "bling_integration_id": None, "bling_loja_id": None,
            "bling_order_id": None, "bling_order_number": None,
        }])
        fake_db = MagicMock()
        fake_db.table.return_value = query
        fake_db.rpc.return_value = query

        with patch.object(service, "supabase_db", fake_db), \
             patch.object(service.canonical_order_repository, "resolve_module_id", return_value="shopee"):
            result = service._process_bling_reference_webhook(
                {"id": 987, "numero": "466320", "numeroLoja": "SN123",
                 "loja": {"id": "204047801"}},
                {},
                {"id": 99},
                {"ingest_origin_mode": "marketplace_direct",
                 "marketplace_integration_id": 12},
                correlation_id="cid",
                webhook_event_id=123,
            )

        self.assertEqual(result["event_status"], "reference_applied")
        self.assertEqual(result["pedido_id"], 77)
        fake_db.rpc.assert_called_once_with(
            "enrich_order_erp_reference",
            {
                "p_pedido_id": 77, "p_erp_integration_id": 99,
                "p_erp_store_id": "204047801", "p_erp_order_id": 987,
                "p_erp_order_number": "466320",
                "p_marketplace_order_id": "SN123",
            },
        )

    def test_reference_only_webhook_defers_when_marketplace_order_is_not_materialized(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[])
        fake_db = MagicMock()
        fake_db.table.return_value = query

        with patch.object(service, "supabase_db", fake_db), \
             patch.object(service.canonical_order_repository, "resolve_module_id", return_value="shopee"), \
             patch.object(service.canonical_order_repository, "defer_unresolved_erp_order") as defer:
            result = service._process_bling_reference_webhook(
                {"id": 987, "numero": "466320", "numeroLoja": "SN123",
                 "loja": {"id": "204047801"}},
                {},
                {"id": 99},
                {"ingest_origin_mode": "marketplace_direct",
                 "marketplace_integration_id": 12},
                correlation_id="cid",
                webhook_event_id=123,
            )

        self.assertEqual(result["event_status"], "reference_pending")
        defer.assert_called_once()
        self.assertEqual(defer.call_args.kwargs["reason"], "direct_marketplace_reference")
        self.assertEqual(defer.call_args.kwargs["erp_order_number"], "466320")

    def test_reference_only_webhook_does_not_overwrite_conflicting_reference(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{
            "id": 77, "erp_integration_id": 100, "erp_store_id": "204047801",
            "erp_order_id": 111, "erp_order_number": "OLD",
            "bling_integration_id": 100, "bling_loja_id": "204047801",
            "bling_order_id": 111, "bling_order_number": "OLD",
        }])
        fake_db = MagicMock()
        fake_db.table.return_value = query

        with patch.object(service, "supabase_db", fake_db), \
             patch.object(service.canonical_order_repository, "resolve_module_id", return_value="shopee"), \
             patch.object(service.canonical_order_repository, "defer_unresolved_erp_order") as defer:
            result = service._process_bling_reference_webhook(
                {"id": 987, "numero": "466320", "numeroLoja": "SN123",
                 "loja": {"id": "204047801"}},
                {},
                {"id": 99},
                {"ingest_origin_mode": "marketplace_direct",
                 "marketplace_integration_id": 12},
                correlation_id="cid",
                webhook_event_id=123,
            )

        self.assertEqual(result["event_status"], "reference_conflict")
        defer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
