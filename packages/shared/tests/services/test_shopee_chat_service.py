import unittest
from unittest.mock import MagicMock, patch

import requests

from nistiprint_shared.services.shopee_chat_api import (
    get_all_chat_messages,
    get_chat_messages,
)
from nistiprint_shared.services.shopee_chat_api import message_timestamp
from nistiprint_shared.services.shopee_chat_service import (
    classify_shopee_webhook,
    extract_chat_provider_event_id,
    identidade_do_comprador,
    normalize_chat_message,
    shopee_chat_ingest_service,
)


def notification_push(tipo="mark_as_replied", conversation_id="4670954831706433"):
    return {
        "code": 10,
        "shop_id": 165103149,
        "data": {
            "type": "notification",
            "content": {
                "type": tipo,
                "conversation_id": conversation_id,
                "content": {"conversation_id": conversation_id},
                "business_type": 0,
            },
        },
    }


def bundle_push(messages=("111", "222")):
    return message_push(
        message_id="999",
        message_type="bundle_message",
        content={"type": 1, "messages": list(messages), "shopee_chatbot_replied": False},
    )


def _db_mock(ids_presentes=()):
    db = MagicMock()
    db.table.return_value.upsert.return_value.execute.return_value.data = []
    db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": ident} for ident in ids_presentes
    ]
    db.rpc.return_value.execute.return_value.data = {"status_completude": "completa",
                                                     "ids_nao_recuperados": []}
    return db


MESSAGE_CONTENT = {
    "message_id": "2302748948493123953",
    "shop_id": 165103149,
    "request_id": "request-1",
    "from_id": 165105353,
    "from_user_name": "buyer",
    "to_id": 947151379,
    "to_user_name": "seller",
    "message_type": "text",
    "content": {"text": "Oi"},
    "conversation_id": "709122092476686867",
    "created_timestamp": 1726044721,
    "region": "BR",
    "business_type": 0,
    "is_in_chatbot_session": False,
    "quoted_msg": {"message_id": ""},
    "sub_account_id": 0,
    "sub_account_name": "0",
}


def message_push(**overrides):
    content = {**MESSAGE_CONTENT, **overrides}
    return {
        "msg_id": "",
        "data": {"type": "message", "region": "BR", "content": content},
        "shop_id": 165103149,
        "code": 10,
        "timestamp": 1726044722,
    }


class ShopeeChatServiceTest(unittest.TestCase):
    def test_classifies_chat_and_order_codes(self):
        self.assertEqual(classify_shopee_webhook({"code": 10}), "chat")
        self.assertEqual(classify_shopee_webhook({"code": 3}), "order")

    def test_uses_nested_message_id_for_push_deduplication(self):
        self.assertEqual(
            extract_chat_provider_event_id(message_push()),
            MESSAGE_CONTENT["message_id"],
        )

    def test_normalizes_documented_message_types(self):
        contents = {
            "text": {"text": "Oi"},
            "video": {"video_url": "https://example/video.mp4"},
            "image": {"image_url": "https://example/image.jpg"},
            "item": {"item_id": 123, "shop_id": 456},
            "faq_liveagent": {"text": "FAQ"},
        }
        for message_type, content in contents.items():
            with self.subTest(message_type=message_type):
                row = normalize_chat_message(
                    {**MESSAGE_CONTENT, "message_type": message_type, "content": content},
                    integration_id=7,
                )
                self.assertEqual(row["type"], message_type)
                self.assertEqual(row["content"], content)
                self.assertEqual(row["provider_message_id"], MESSAGE_CONTENT["message_id"])
                self.assertEqual(row["business_type"], 0)

    def test_mark_as_replied_pede_varredura_em_vez_de_ser_descartado(self):
        """A Shopee nao faz push da mensagem enviada pela loja.

        `mark_as_replied` e o unico sinal de que houve resposta. Descarta-lo, como
        se fazia antes, e o motivo de nao existir uma unica mensagem da loja
        espelhada no banco.
        """
        db = _db_mock()
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db", db
        ):
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7, "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(notification_push())

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["event_status"], "chat_sincronizacao_solicitada")
        db.table.assert_any_call("conversas_chat_shopee")
        linha = db.table.return_value.upsert.call_args.args[0]
        self.assertEqual(linha["conversation_id"], 4670954831706433)
        self.assertIsNotNone(linha["sincronizacao_solicitada_em"])

    def test_outras_notificacoes_continuam_sendo_ignoradas(self):
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db"
        ) as db:
            result = shopee_chat_ingest_service.process(notification_push(tipo="read"))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["event_status"], "skipped_chat_notification")
        resolver.resolve_marketplace_by_shop_id.assert_not_called()
        db.table.assert_not_called()

    def test_bundle_e_resolvido_por_id_no_proprio_push(self):
        """O caminho quente: uma chamada com `message_id_list`, sem paginacao."""
        db = _db_mock()
        filhas = [
            {**MESSAGE_CONTENT, "message_id": "111", "content": {"text": "Miguel"}},
            {**MESSAGE_CONTENT, "message_id": "222", "content": {"text": "com Y"}},
        ]
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db", db
        ), patch(
            "nistiprint_shared.services.shopee_chat_service.get_chat_messages",
            return_value={"messages": filhas},
        ) as buscar, patch.object(
            shopee_chat_ingest_service, "_integracao_hidratada",
            return_value={"id": 7, "config": {"shop_id": 165103149}},
        ):
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7, "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(bundle_push())

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["event_status"], "chat_persisted_bundle_resolvido")
        self.assertEqual(buscar.call_count, 1)
        self.assertEqual(buscar.call_args.kwargs["message_id_list"], ["111", "222"])
        gravadas = [
            chamada.args[0] for chamada in db.table.return_value.upsert.call_args_list
            if isinstance(chamada.args[0], list)
        ]
        self.assertIn(
            {"111", "222"},
            [{linha["provider_message_id"] for linha in lote} for lote in gravadas],
        )

    def test_bundle_ja_resolvido_nao_chama_a_shopee(self):
        db = _db_mock(ids_presentes=("111", "222"))
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db", db
        ), patch(
            "nistiprint_shared.services.shopee_chat_service.get_chat_messages"
        ) as buscar, patch.object(
            shopee_chat_ingest_service, "_integracao_hidratada",
            return_value={"id": 7, "config": {}},
        ):
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7, "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(bundle_push())
        buscar.assert_not_called()
        self.assertEqual(result["status"], "success")

    def test_falha_na_shopee_nao_derruba_o_webhook_do_bundle(self):
        """O push ja esta gravado e a conversa consta como pendente.

        Devolver erro aqui so faria o evento repetir o mesmo caminho e, no limite,
        ir para a DLQ por indisponibilidade de terceiro. Quem tenta de novo, com
        backoff, e a varredura.
        """
        db = _db_mock()
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db", db
        ), patch(
            "nistiprint_shared.services.shopee_chat_service.get_chat_messages",
            return_value={"error": "Erro na API SellerChat: 429",
                          "error_type": "rate_limit", "retryable": True},
        ), patch.object(
            shopee_chat_ingest_service, "_integracao_hidratada",
            return_value={"id": 7, "config": {}},
        ):
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7, "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(bundle_push())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["event_status"], "chat_persisted_bundle_pendente")
        self.assertEqual(result["bundle_erro"], "rate_limit")

    def test_lote_repetido_pela_paginacao_nao_quebra_o_upsert(self):
        """O Postgres recusa um ON CONFLICT que afete a mesma linha duas vezes."""
        db = _db_mock()
        repetidas = [MESSAGE_CONTENT, dict(MESSAGE_CONTENT)]
        with patch("nistiprint_shared.services.shopee_chat_service.supabase_db", db):
            linhas = shopee_chat_ingest_service._persistir(
                repetidas, integration_id=7, shop_id=1, ingestion_source="sellerchat_api"
            )
        self.assertEqual(len(linhas), 1)

    def test_comprador_e_o_participante_que_nao_e_a_loja(self):
        """Na Shopee o comprador tambem tem shop_id proprio."""
        mensagem_do_comprador = {
            "from_id": 697040328, "from_user_name": "roberta", "from_shop_id": 697020000,
            "to_id": 376241283, "to_user_name": "nisti_print", "to_shop_id": 376221706,
        }
        self.assertEqual(
            identidade_do_comprador(mensagem_do_comprador, 376221706),
            (697040328, "roberta"),
        )
        mensagem_da_loja = {
            "from_id": 376241283, "from_user_name": "nisti_print", "from_shop_id": 376221706,
            "to_id": 697040328, "to_user_name": "roberta", "to_shop_id": 697020000,
        }
        self.assertEqual(
            identidade_do_comprador(mensagem_da_loja, 376221706),
            (697040328, "roberta"),
        )

    def test_affiliate_chat_is_skipped(self):
        result = shopee_chat_ingest_service.process(message_push(business_type=11))
        self.assertEqual(result["event_status"], "skipped_affiliate_chat")

    def test_documented_message_envelope_is_upserted(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value.data = []
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver, patch(
            "nistiprint_shared.services.shopee_chat_service.supabase_db", db
        ):
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7,
                "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(message_push(), webhook_event_id=88)
        self.assertEqual(result["status"], "success")
        rows = db.table.return_value.upsert.call_args.args[0]
        self.assertEqual(rows[0]["provider_message_id"], MESSAGE_CONTENT["message_id"])
        self.assertEqual(rows[0]["webhook_event_id"], 88)
        self.assertEqual(
            db.table.return_value.upsert.call_args.kwargs["on_conflict"],
            "installed_integration_id,provider_message_id",
        )

    def test_malformed_message_is_retryable_error(self):
        payload = message_push(message_id=None)
        with patch(
            "nistiprint_shared.services.shopee_chat_service.integration_resolution_service"
        ) as resolver:
            resolver.resolve_marketplace_by_shop_id.return_value = {
                "id": 7,
                "plataforma_slug": "shopee",
            }
            result = shopee_chat_ingest_service.process(payload)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "invalid_chat_message")

    def test_reconciliation_upserts_complete_api_history(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value.data = []
        with patch(
            "nistiprint_shared.services.shopee_chat_service.get_all_chat_messages",
            return_value={"messages": [MESSAGE_CONTENT], "complete": True},
        ), patch("nistiprint_shared.services.shopee_chat_service.supabase_db", db):
            result = shopee_chat_ingest_service.reconcile_conversation(
                {"id": 7, "config": {"shop_id": 165103149}},
                MESSAGE_CONTENT["conversation_id"],
            )
        self.assertEqual(result["status"], "success")
        rows = db.table.return_value.upsert.call_args.args[0]
        self.assertEqual(rows[0]["ingestion_source"], "sellerchat_api")


class VarreduraDeConversasTest(unittest.TestCase):
    """A rede de seguranca. A fila e a tabela, nao o Redis: ela sobrevive a
    reinicio e nao depende de o evento original ainda existir."""

    def _db(self, solicitadas, vencidas):
        db = MagicMock()
        select = db.table.return_value.select.return_value
        (select.not_.is_.return_value.lte.return_value.order.return_value
         .limit.return_value.execute.return_value.data) = solicitadas
        (select.in_.return_value.lte.return_value.order.return_value
         .limit.return_value.execute.return_value.data) = vencidas
        return db

    def test_com_ids_conhecidos_resolve_pontualmente(self):
        db = self._db([], [{"conversation_id": 5, "installed_integration_id": 7,
                            "ids_nao_recuperados": ["111"], "status_completude": "pendente",
                            "sincronizacao_solicitada_em": None, "tentativas": 1}])
        with patch("nistiprint_shared.services.shopee_chat_service.supabase_db", db), \
             patch.object(shopee_chat_ingest_service, "_integracao_hidratada",
                          return_value={"id": 7, "config": {}}), \
             patch.object(shopee_chat_ingest_service, "resolver_bundle",
                          return_value={"status": "success", "status_completude": "completa",
                                        "messages_upserted": 1}) as pontual, \
             patch.object(shopee_chat_ingest_service, "reconcile_conversation") as completo:
            resumo = shopee_chat_ingest_service.varrer_conversas_pendentes()
        pontual.assert_called_once()
        completo.assert_not_called()
        self.assertEqual(resumo["completas"], 1)

    def test_resposta_da_loja_pede_varredura_completa(self):
        db = self._db([{"conversation_id": 5, "installed_integration_id": 7,
                        "ids_nao_recuperados": [], "status_completude": "completa",
                        "sincronizacao_solicitada_em": "2026-09-07T10:00:00+00:00",
                        "tentativas": 0}], [])
        with patch("nistiprint_shared.services.shopee_chat_service.supabase_db", db), \
             patch.object(shopee_chat_ingest_service, "_integracao_hidratada",
                          return_value={"id": 7, "config": {}}), \
             patch.object(shopee_chat_ingest_service, "reconcile_conversation",
                          return_value={"status": "success", "status_completude": "completa",
                                        "messages_upserted": 3}) as completo, \
             patch.object(shopee_chat_ingest_service, "_limpar_solicitacao") as limpar:
            resumo = shopee_chat_ingest_service.varrer_conversas_pendentes()
        completo.assert_called_once()
        limpar.assert_called_once_with(5)
        self.assertEqual(resumo["mensagens_recuperadas"], 3)

    def test_falha_adia_a_solicitacao_em_vez_de_repetir_todo_ciclo(self):
        """Sem o adiamento, `chatsync` viraria um laco quente contra uma API fora."""
        db = self._db([{"conversation_id": 5, "installed_integration_id": 7,
                        "ids_nao_recuperados": [], "status_completude": "pendente",
                        "sincronizacao_solicitada_em": "2026-09-07T10:00:00+00:00",
                        "tentativas": 2}], [])
        with patch("nistiprint_shared.services.shopee_chat_service.supabase_db", db), \
             patch.object(shopee_chat_ingest_service, "_integracao_hidratada",
                          return_value={"id": 7, "config": {}}), \
             patch.object(shopee_chat_ingest_service, "reconcile_conversation",
                          return_value={"status": "error", "error_type": "rate_limit"}), \
             patch.object(shopee_chat_ingest_service, "_adiar_solicitacao") as adiar, \
             patch.object(shopee_chat_ingest_service, "_limpar_solicitacao") as limpar:
            resumo = shopee_chat_ingest_service.varrer_conversas_pendentes()
        adiar.assert_called_once_with(5, 2)
        limpar.assert_not_called()
        self.assertEqual(resumo["falhas"], 1)

    def test_conversa_sem_integracao_ativa_nao_trava_a_fila(self):
        db = self._db([], [{"conversation_id": 5, "installed_integration_id": 99,
                            "ids_nao_recuperados": ["111"], "status_completude": "pendente",
                            "sincronizacao_solicitada_em": None, "tentativas": 0}])
        with patch("nistiprint_shared.services.shopee_chat_service.supabase_db", db), \
             patch.object(shopee_chat_ingest_service, "_integracao_hidratada",
                          return_value=None), \
             patch.object(shopee_chat_ingest_service, "_atualizar_completude") as recalcular:
            resumo = shopee_chat_ingest_service.varrer_conversas_pendentes()
        self.assertEqual(resumo["sem_integracao"], 1)
        recalcular.assert_called_once()


class ShopeeChatApiTest(unittest.TestCase):
    def setUp(self):
        self.integration = {
            "config": {"partner_id": 1, "partner_key": "secret", "shop_id": 2},
            "access_token": "token",
        }

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_uses_string_offset_and_reads_nested_next_offset(self, request_get):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "error": "",
            "response": {
                "messages": [MESSAGE_CONTENT],
                "page_result": {
                    "next_offset": "922337203685477580812345",
                    "page_size": 1,
                },
            },
        }
        request_get.return_value = response
        result = get_chat_messages(
            self.integration,
            "conversation-1",
            offset="922337203685477580799999",
            message_id_list=["2302748948493123953"],
        )
        params = request_get.call_args.kwargs["params"]
        self.assertEqual(params["offset"], "922337203685477580799999")
        self.assertEqual(params["business_type"], 0)
        self.assertEqual(result["next_offset"], "922337203685477580812345")

    @patch("nistiprint_shared.services.shopee_chat_api.get_chat_messages")
    def test_fetches_all_pages(self, get_page):
        get_page.side_effect = [
            {"messages": [{"message_id": "2"}], "next_offset": "2"},
            {"messages": [{"message_id": "1"}], "next_offset": None},
        ]
        result = get_all_chat_messages(self.integration, "conversation-1")
        self.assertTrue(result["complete"])
        self.assertEqual([row["message_id"] for row in result["messages"]], ["2", "1"])
        self.assertEqual(get_page.call_args_list[1].kwargs["offset"], "2")

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_classifies_rate_limit_and_auth_errors(self, request_get):
        rate_limited = MagicMock(status_code=429, text="rate limited", headers={"Retry-After": "17"})
        unauthorized = MagicMock(status_code=401, text="unauthorized")
        request_get.side_effect = [rate_limited, unauthorized]
        rate_result = get_chat_messages(self.integration, "conversation-1")
        auth_result = get_chat_messages(self.integration, "conversation-1")
        self.assertEqual(rate_result["error_type"], "rate_limit")
        self.assertTrue(rate_result["retryable"])
        self.assertEqual(rate_result["retry_after"], 17)
        self.assertEqual(auth_result["error_type"], "authentication_error")
        self.assertFalse(auth_result["retryable"])

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_lista_vai_separada_por_virgula(self, request_get):
        """A Shopee recusa a chave repetida com `param_error` e HTTP 491.

        O array vai como string separada por virgula, igual ao `order_sn_list` do
        get_order_detail -- a chamada Shopee que ja funciona neste codigo.
        """
        response = MagicMock(status_code=200)
        response.json.return_value = {"error": "", "response": {"messages": []}}
        request_get.return_value = response
        get_chat_messages(self.integration, "conversation-1",
                          message_id_list=["111", "222", "333"])
        params = request_get.call_args.kwargs["params"]
        self.assertEqual(params["message_id_list"], "111,222,333")

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_page_size_respeita_o_teto_documentado_de_60(self, request_get):
        """`page_size` acima de 60 e `param_error`, nao truncamento silencioso."""
        response = MagicMock(status_code=200)
        response.json.return_value = {"error": "", "response": {"messages": []}}
        request_get.return_value = response
        get_chat_messages(self.integration, "conversation-1", page_size=100)
        self.assertEqual(request_get.call_args.kwargs["params"]["page_size"], 60)

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_param_error_em_491_nao_e_tratado_como_limite_de_taxa(self, request_get):
        """491 nao e status HTTP padrao; quem diz o motivo e o corpo.

        Classificar pelo status faria um erro permanente de parametro ser
        repetido para sempre com espera de rate limit.
        """
        response = MagicMock(status_code=491, text='{"error":"param_error"}')
        response.json.return_value = {
            "error": "param_error",
            "message": "Error or loss in request parameter.",
        }
        request_get.return_value = response
        result = get_chat_messages(self.integration, "conversation-1")
        self.assertEqual(result["error_type"], "parameter_error")
        self.assertFalse(result["retryable"])
        self.assertEqual(result["code"], "param_error")
        self.assertIn("Error or loss in request parameter", result["error"])

    @patch("nistiprint_shared.services.shopee_chat_api.get_chat_messages")
    def test_para_de_paginar_ao_sair_da_janela(self, get_page):
        """Paginar ate o inicio da conversa e a lentidao que impede reconciliar."""
        get_page.side_effect = [
            {"messages": [{"message_id": "3", "created_timestamp": 2_000}], "next_offset": "2"},
            {"messages": [{"message_id": "2", "created_timestamp": 900}], "next_offset": "1"},
            {"messages": [{"message_id": "1", "created_timestamp": 100}], "next_offset": None},
        ]
        result = get_all_chat_messages(self.integration, "conversation-1", desde_epoch=1_000)
        self.assertTrue(result["parou_na_janela"])
        self.assertEqual(get_page.call_count, 2)

    @patch("nistiprint_shared.services.shopee_chat_api.get_chat_messages")
    def test_ordem_invertida_degrada_para_varredura_completa(self, get_page):
        """A ordem das paginas nao e contrato publicado da Shopee.

        Se a mais antiga vier primeiro, parar na primeira pagina fora da janela
        devolveria zero mensagens -- pior que paginar demais.
        """
        get_page.side_effect = [
            {"messages": [{"message_id": "1", "created_timestamp": 100}], "next_offset": "2"},
            {"messages": [{"message_id": "2", "created_timestamp": 2_000}], "next_offset": None},
        ]
        result = get_all_chat_messages(self.integration, "conversation-1", desde_epoch=1_000)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["messages"]), 2)

    def test_le_o_epoch_nos_tres_nomes_que_a_shopee_usa(self):
        self.assertEqual(message_timestamp({"created_timestamp": 5}), 5)
        self.assertEqual(message_timestamp({"timestamp": "7"}), 7)
        self.assertIsNone(message_timestamp({"created_timestamp": ""}))

    @patch(
        "nistiprint_shared.services.shopee_chat_api.requests.get",
        side_effect=requests.Timeout("timeout"),
    )
    def test_classifies_timeout_as_retryable(self, _request_get):
        result = get_chat_messages(self.integration, "conversation-1")
        self.assertEqual(result["error_type"], "timeout")
        self.assertTrue(result["retryable"])

    @patch("nistiprint_shared.services.shopee_chat_api.requests.get")
    def test_invalid_json_is_retryable(self, request_get):
        response = MagicMock(status_code=200, text="gateway garbage")
        response.json.side_effect = ValueError("invalid json")
        request_get.return_value = response
        result = get_chat_messages(self.integration, "conversation-1")
        self.assertEqual(result["error_type"], "invalid_response")
        self.assertTrue(result["retryable"])


if __name__ == "__main__":
    unittest.main()
