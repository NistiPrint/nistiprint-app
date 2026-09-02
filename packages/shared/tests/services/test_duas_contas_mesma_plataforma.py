"""Duas contas do mesmo marketplace chegando pelo mesmo endpoint.

O Mercado Livre entrega as notificacoes de todas as contas na mesma rota; quem
diz de quem e o evento e o `user_id` do corpo. Estes testes cobrem a decisao
inteira, incluindo os modos de falhar. O que nao pode acontecer, nunca, e um
evento da conta B ser processado com a credencial da conta A.
"""
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import credential_resolver_service as cr_module
from nistiprint_shared.services.credential_resolver_service import (
    AmbiguousAppProfileError,
    credential_resolver_service,
)
from nistiprint_shared.services.marketplace_account_identity import (
    account_identity_matches,
    merge_account_identity_config,
)
from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    MarketplaceWebhookIngestService,
)
from nistiprint_shared.services.reliable_ingest_service import extract_identity

CONTA_A = "207584268"
CONTA_B = "999888777"

INTEGRACAO_A = {
    "id": 7091, "module_id": "mercadolivre", "instance_name": "Mercado Livre",
    "app_profile_id": 5, "is_active": True,
    "config": {"account_identifiers": {"kind": "user_id", "primary": CONTA_A, "aliases": []}},
}
INTEGRACAO_B = {
    "id": 7093, "module_id": "mercadolivre", "instance_name": "Mercado Livre CNPJ03",
    "app_profile_id": 6, "is_active": True,
    "config": {"account_identifiers": {"kind": "user_id", "primary": CONTA_B, "aliases": []}},
}

PROFILE_A = {"id": 5, "module_id": "mercadolivre", "name": "ML CNPJ01", "is_active": True}
PROFILE_B = {"id": 6, "module_id": "mercadolivre", "name": "ML CNPJ03", "is_active": True}


def _envelope(user_id, notification_id, resource="/orders/2000018168181820"):
    """Envelope como o n8n monta hoje, com a conta resolvida na borda."""
    body = {
        "_id": notification_id, "resource": resource, "user_id": int(user_id),
        "topic": "orders_v2", "application_id": 1234567890123456,
        "sent": "2026-09-01T18:00:00.000Z",
    }
    return {
        "schema_version": 1, "event_id": f"evt-{notification_id}",
        "source": "mercadolivre", "received_at": "2026-09-01T21:00:00.000Z",
        "raw_body": "{}", "parsed_payload": body,
        "body_sha256": f"hash-{notification_id}",
        "provider_delivery_id": notification_id,
        "account_id": str(user_id), "application_id": "1234567890123456",
    }


class ResolucaoDaContaTest(unittest.TestCase):
    def setUp(self):
        self.service = MarketplaceWebhookIngestService()

    def _resolver(self, identificador, integracoes):
        with patch.object(
            self.service, "_active_marketplace_integrations", return_value=integracoes
        ):
            return self.service._resolve_marketplace_integration(
                "mercadolivre", account_identifier=identificador
            )

    def test_cada_conta_resolve_para_a_sua_integracao(self):
        inst, erro = self._resolver(CONTA_A, [INTEGRACAO_A, INTEGRACAO_B])
        self.assertIsNone(erro)
        self.assertEqual(inst["id"], 7091)

        inst, erro = self._resolver(CONTA_B, [INTEGRACAO_A, INTEGRACAO_B])
        self.assertIsNone(erro)
        self.assertEqual(inst["id"], 7093)

    def test_conta_desconhecida_espera_o_cadastro_em_vez_de_sumir(self):
        inst, erro = self._resolver("111222333", [INTEGRACAO_A, INTEGRACAO_B])
        self.assertIsNone(inst)
        self.assertEqual(erro["error_type"], "marketplace_integration_not_found")
        self.assertTrue(erro["retryable"])

    def test_evento_sem_identificador_nao_e_atribuido_a_ninguem(self):
        inst, erro = self._resolver(None, [INTEGRACAO_A, INTEGRACAO_B])
        self.assertIsNone(inst)
        self.assertEqual(erro["error_type"], "marketplace_integration_ambiguous")
        self.assertFalse(erro["retryable"])
        self.assertEqual(sorted(erro["candidate_integration_ids"]), [7091, 7093])

    def test_identificador_duplicado_entre_contas_e_recusado(self):
        clone = {**INTEGRACAO_B, "config": INTEGRACAO_A["config"]}
        inst, erro = self._resolver(CONTA_A, [INTEGRACAO_A, clone])
        self.assertIsNone(inst)
        self.assertEqual(erro["error_type"], "marketplace_integration_ambiguous")

    def test_integracao_sem_identidade_nao_absorve_a_outra_conta(self):
        sem_identidade = {**INTEGRACAO_B, "config": {}}
        inst, erro = self._resolver(CONTA_B, [INTEGRACAO_A, sem_identidade])
        self.assertIsNone(inst)
        self.assertEqual(erro["error_type"], "marketplace_integration_not_found")


class DedupeIsoladoPorContaTest(unittest.TestCase):
    def test_contas_diferentes_nao_colidem(self):
        a = extract_identity(_envelope(CONTA_A, "notif-1"))
        b = extract_identity(_envelope(CONTA_B, "notif-2"))
        self.assertEqual(a["dedupe_scope"], CONTA_A)
        self.assertEqual(b["dedupe_scope"], CONTA_B)
        self.assertNotEqual((a["dedupe_scope"], a["dedupe_key"]),
                            (b["dedupe_scope"], b["dedupe_key"]))

    def test_mesmo_pedido_com_notificacoes_diferentes_nao_colide(self):
        """A regressao que descartou 4.123 notificacoes em 30 dias."""
        primeira = extract_identity(_envelope(CONTA_A, "notif-1"))
        segunda = extract_identity(_envelope(CONTA_A, "notif-2"))
        self.assertNotEqual(primeira["dedupe_key"], segunda["dedupe_key"])

    def test_reentrega_da_mesma_notificacao_colide_de_proposito(self):
        primeira = extract_identity(_envelope(CONTA_A, "notif-1"))
        reentrega = extract_identity(_envelope(CONTA_A, "notif-1"))
        self.assertEqual(primeira["dedupe_key"], reentrega["dedupe_key"])
        self.assertEqual(primeira["dedupe_scope"], reentrega["dedupe_scope"])

    def test_conta_da_borda_vence_o_corpo(self):
        envelope = _envelope(CONTA_A, "notif-1")
        envelope["account_id"] = CONTA_B
        self.assertEqual(extract_identity(envelope)["dedupe_scope"], CONTA_B)

    def test_envelope_antigo_sem_account_id_ainda_resolve_pelo_corpo(self):
        envelope = _envelope(CONTA_A, "notif-1")
        del envelope["account_id"]
        self.assertEqual(extract_identity(envelope)["dedupe_scope"], CONTA_A)


class CredencialPorContaTest(unittest.TestCase):
    def setUp(self):
        cr_module._WARNED_LEGACY_BOOTSTRAP.clear()

    def _profile(self, instalacao):
        with patch.object(
            cr_module.integration_app_profile_service, "list_profiles",
            return_value=[PROFILE_A, PROFILE_B],
        ), patch.object(
            cr_module.integration_app_profile_service, "get_profile",
            side_effect=lambda pid: {5: PROFILE_A, 6: PROFILE_B}.get(pid),
        ):
            return credential_resolver_service._resolve_app_profile(
                instalacao, "mercadolivre"
            )

    def test_cada_integracao_usa_o_seu_aplicativo(self):
        self.assertEqual(self._profile(INTEGRACAO_A)["id"], 5)
        self.assertEqual(self._profile(INTEGRACAO_B)["id"], 6)

    def test_instalacao_sem_vinculo_recusa_em_vez_de_herdar(self):
        """O acidente que queima o refresh token rotativo da conta B."""
        with self.assertRaises(AmbiguousAppProfileError):
            self._profile({**INTEGRACAO_B, "app_profile_id": None})

    def test_ambiente_nao_e_consultado_havendo_profiles(self):
        with patch.dict(
            cr_module.os.environ,
            {"ML_CNPJ01_CLIENT_ID": "app-a", "ML_CNPJ01_CLIENT_SECRET": "segredo-a"},
            clear=False,
        ), patch.object(
            cr_module.integration_app_profile_service, "list_profiles",
            return_value=[PROFILE_A, PROFILE_B],
        ), patch.object(
            cr_module.integration_app_profile_service, "get_profile",
            side_effect=lambda pid: {5: PROFILE_A, 6: PROFILE_B}.get(pid),
        ), patch.object(
            cr_module.integration_secret_service, "get_secret_map", return_value={}
        ), patch.object(
            credential_resolver_service, "_legacy_env_bootstrap"
        ) as bootstrap:
            credential_resolver_service.resolve_for_installation(dict(INTEGRACAO_B))
        bootstrap.assert_not_called()


class IdentidadeGravadaNoOauthTest(unittest.TestCase):
    def test_identidade_do_oauth_casa_com_o_user_id_do_evento(self):
        config = merge_account_identity_config(
            {}, "mercadolivre", CONTA_B, source="oauth"
        )
        integracao = {"config": config, "credentials": {}}
        self.assertEqual(config["account_identifiers"]["kind"], "user_id")
        self.assertTrue(account_identity_matches(integracao, CONTA_B))
        self.assertTrue(account_identity_matches(integracao, int(CONTA_B)))
        self.assertFalse(account_identity_matches(integracao, CONTA_A))


class RoteamentoPorContaTest(unittest.TestCase):
    """Cada conta rota para o seu Bling, sua loja e seu canal."""

    def setUp(self):
        self.service = MarketplaceWebhookIngestService()

    def _link(self, integration_id, linhas):
        fake = MagicMock()

        def table(nome):
            query = MagicMock()
            for metodo in ("select", "eq", "limit", "order"):
                getattr(query, metodo).return_value = query
            query.execute.return_value = MagicMock(data=linhas.get(nome, []))
            return query

        fake.table.side_effect = table
        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.supabase_db",
            fake,
        ):
            return self.service._find_direct_ingest_link(integration_id)

    def test_conta_b_rota_para_o_bling_da_conta_b(self):
        link = self._link(7093, {"erp_marketplace_links": [{
            "id": "cnpj03", "erp_integration_id": 3, "marketplace_integration_id": 7093,
            "process_webhooks": True, "ingest_origin_mode": "erp_bling",
            "erp_store_id": "205421972", "channel_id": 9,
        }]})
        self.assertEqual(link["bling_integration_id"], 3)
        self.assertEqual(link["aggregator_store_id"], "205421972")
        self.assertEqual(link["ingest_origin_mode"], "erp_bling")

    def test_conta_a_segue_no_bling_da_conta_a(self):
        link = self._link(7091, {"erp_marketplace_links": [{
            "id": "cnpj01", "erp_integration_id": 1, "marketplace_integration_id": 7091,
            "process_webhooks": True, "ingest_origin_mode": "marketplace_direct",
            "erp_store_id": "203753446", "channel_id": 9,
        }]})
        self.assertEqual(link["bling_integration_id"], 1)
        self.assertEqual(link["ingest_origin_mode"], "marketplace_direct")

    def test_conta_com_webhooks_desligados_e_pulada_sem_erro(self):
        link = self._link(7093, {"erp_marketplace_links": [{
            "id": "cnpj03", "erp_integration_id": 3, "marketplace_integration_id": 7093,
            "process_webhooks": False, "ingest_origin_mode": "erp_bling",
            "erp_store_id": "205421972", "channel_id": 9,
        }]})
        resultado = self.service._inactive_source_result(
            "mercadolivre", link, "2000018168181820", {"id": 7093}
        )
        self.assertEqual(resultado["status"], "skipped")
        self.assertEqual(resultado["skip_reason"], "webhooks_disabled")
