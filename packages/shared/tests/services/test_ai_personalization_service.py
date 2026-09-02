import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import ai_personalization_service as service


class TestAiPersonalizationService(unittest.TestCase):
    def test_should_process_order_without_buyer_signal(self):
        self.assertFalse(
            service.should_process_order({
                "message_to_seller": "",
                "last_buyer_message_at": None,
                "last_ai_executed_at": None,
            })
        )

    def test_should_process_order_on_first_run_with_chat_only(self):
        self.assertTrue(
            service.should_process_order({
                "message_to_seller": "",
                "has_chat_messages": True,
                "last_buyer_message_at": None,
                "last_ai_executed_at": None,
            })
        )

    def test_should_process_order_on_first_run_with_message_to_seller(self):
        self.assertTrue(
            service.should_process_order({
                "message_to_seller": "Nome: Maria",
                "last_buyer_message_at": None,
                "last_ai_executed_at": None,
            })
        )

    def test_should_process_order_when_buyer_replied_after_last_execution(self):
        self.assertTrue(
            service.should_process_order({
                "message_to_seller": "Nome: Maria",
                "last_ai_executed_at": "2026-06-17T10:00:00+00:00",
                "last_buyer_message_at": "2026-06-17T11:00:00+00:00",
                "ai_status": "success",
            })
        )

    def test_should_not_process_when_only_old_buyer_signal_exists(self):
        self.assertFalse(
            service.should_process_order({
                "message_to_seller": "Nome: Maria",
                "last_ai_executed_at": "2026-06-17T11:00:00+00:00",
                "last_buyer_message_at": "2026-06-17T10:00:00+00:00",
                "ai_status": "success",
            })
        )

    def test_compact_chat_messages_removes_seller_noise(self):
        messages = [
            {
                "id": "1",
                "from_user_name": "lojista",
                "to_user_name": "cliente123",
                "created_at": "2026-06-17T10:00:00",
                "type": "text",
                "display_content": "Boa tarde",
            },
            {
                "id": "2",
                "from_user_name": "cliente123",
                "to_user_name": "lojista",
                "created_at": "2026-06-17T10:01:00",
                "type": "text",
                "display_content": "Pode corrigir para Ana Clara",
            },
            {
                "id": "3",
                "from_user_name": "lojista",
                "to_user_name": "cliente123",
                "created_at": "2026-06-17T10:02:00",
                "type": "text",
                "display_content": "Nome para capa confirmado. Ana Clara\n\nSeu pedido entrou para fila de produção e em breve será postado.",
            },
        ]

        compacted = service.compact_chat_messages(messages, "cliente123")

        self.assertEqual(len(compacted), 2)
        self.assertEqual(compacted[0]["sender_role"], "Comprador")
        self.assertEqual(compacted[0]["display_content"], "Pode corrigir para Ana Clara")
        self.assertEqual(compacted[1]["sender_role"], "Vendedor")
        self.assertEqual(compacted[1]["display_content"], "Nome para capa confirmado. Ana Clara")

    def test_fetch_recent_personalized_orders_uses_all_shopee_channel_ids(self):
        query = MagicMock()
        query.select.return_value = query
        query.in_.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.gte.return_value = query
        query.execute.return_value.data = []

        with patch.object(service.supabase_db, "table", return_value=query):
            with patch.object(service, "_get_shopee_channel_ids", return_value=[1, 27]):
                service._fetch_recent_personalized_orders(recent_days=None)

        query.in_.assert_any_call("canal_venda_id", [1, 27])
        query.in_.assert_any_call("situacao_pedido_id", [2, 3, 4])

    def test_processing_selection_uses_only_in_progress_orders(self):
        with patch.object(service, "_assemble_orders", return_value=[]) as assemble:
            service.select_orders_for_processing()

        assemble.assert_called_once_with(
            order_sn=None,
            pedido_ids=None,
            limit=None,
            recent_days=None,
            situacao_ids=[service.STATUS_EM_ANDAMENTO],
        )

    def test_display_selection_includes_production_and_ready_to_ship_orders(self):
        with patch.object(service, "_assemble_orders", return_value=[]) as assemble:
            service.get_orders_with_chats()

        assemble.assert_called_once_with(
            order_sn=None,
            limit=None,
            recent_days=None,
            situacao_ids=[2, 3, 4],
        )

    def test_processing_rejects_later_order_status_even_when_forced(self):
        order = {
            "id": 3,
            "numero_pedido": "123",
            "numero_loja": "SN-123",
            "situacao_pedido_id": 3,
            "itens": [],
        }

        with patch.object(service, "_assemble_orders", return_value=[order]):
            to_process, skipped = service.select_orders_for_processing(force=True)

        self.assertEqual(to_process, [])
        self.assertEqual(skipped[0]["reason"], "status_not_eligible")


class _FakeQuery:
    """Fake minimo do query builder do supabase-py, sobre uma lista de dicts.

    Os testes abaixo checam o ESTADO em que os lotes ficam, nao a sequencia de
    chamadas. Verificar chamadas travaria a implementacao atual; verificar
    estado trava a promessa — nenhum lote fica preso sem alguem para processa-lo.
    """

    def __init__(self, store, tabela):
        self._store = store
        self._tabela = tabela
        self._filtros = []
        self._modo = None
        self._payload = None

    # -- verbos --
    def select(self, *_args, **_kwargs):
        self._modo = "select"
        return self

    def insert(self, payload):
        self._modo, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._modo, self._payload = "update", payload
        return self

    # -- filtros --
    def eq(self, campo, valor):
        self._filtros.append(lambda row, c=campo, v=valor: row.get(c) == v)
        return self

    def lt(self, campo, valor):
        self._filtros.append(lambda row, c=campo, v=valor: str(row.get(c)) < str(v))
        return self

    def _casa(self, row):
        return all(f(row) for f in self._filtros)

    def execute(self):
        linhas = self._store.setdefault(self._tabela, [])
        if self._modo == "insert":
            registro = dict(self._payload)
            registro.setdefault("id", f"batch-{len(linhas) + 1}")
            registro.setdefault("processados", 0)
            linhas.append(registro)
            return SimpleNamespace(data=[registro])

        alvos = [row for row in linhas if self._casa(row)]
        if self._modo == "update":
            for row in alvos:
                row.update(self._payload)
        return SimpleNamespace(data=[dict(row) for row in alvos])


class _FakeDb:
    def __init__(self, store):
        self._store = store

    def table(self, nome):
        return _FakeQuery(self._store, nome)


def _lote(batch_id, status, idade_segundos, total=3, processados=0):
    criado = datetime.now(timezone.utc) - timedelta(seconds=idade_segundos)
    return {
        "id": batch_id,
        "status": status,
        "total": total,
        "processados": processados,
        "criado_em": criado.isoformat(),
        "pedido_ids": list(range(total)),
    }


class TestEnfileiramentoBestEffort(unittest.TestCase):
    """O registro do lote e a fila sao duas escritas sem transacao entre si.

    A regra que estes testes protegem: o Postgres manda. Um broker fora do ar
    atrasa o inicio, mas nunca cancela um lote nem o deixa em estado que
    ninguem vai retomar.
    """

    def setUp(self):
        self.store = {"execucoes_ai_batch": []}
        self.db = _FakeDb(self.store)

    def test_broker_fora_do_ar_mantem_o_lote_pendente(self):
        with patch.object(service, "supabase_db", self.db):
            with patch.object(service.processar_batch_ia, "delay", side_effect=OSError("recusou")):
                resultado = service.create_processing_batch([1, 2, 3])

        self.assertFalse(resultado["enfileirado"])
        # PENDENTE e nao ERRO: o trabalho continua valido e sera retomado.
        self.assertEqual(self.store["execucoes_ai_batch"][0]["status"], "PENDENTE")

    def test_broker_no_ar_marca_como_enfileirado(self):
        with patch.object(service, "supabase_db", self.db):
            with patch.object(service.processar_batch_ia, "delay") as delay:
                resultado = service.create_processing_batch([1, 2, 3])

        self.assertTrue(resultado["enfileirado"])
        delay.assert_called_once()


class TestVarreduraDeLotesParados(unittest.TestCase):
    def setUp(self):
        self.store = {"execucoes_ai_batch": []}
        self.db = _FakeDb(self.store)

    def _rodar(self, delay_mock=None):
        with patch.object(service, "supabase_db", self.db):
            with patch.object(
                service.processar_batch_ia, "delay", delay_mock or MagicMock()
            ):
                return service.recolher_lotes_ia_parados()

    def _status(self, batch_id):
        return next(r for r in self.store["execucoes_ai_batch"] if r["id"] == batch_id)["status"]

    def test_pendente_antigo_e_retomado(self):
        self.store["execucoes_ai_batch"].append(_lote("b1", "PENDENTE", 600))
        delay = MagicMock()

        resultado = self._rodar(delay)

        delay.assert_called_once_with("b1")
        self.assertEqual(resultado["retomados"], ["b1"])
        self.assertEqual(self._status("b1"), "RODANDO")

    def test_pendente_recente_nao_e_tocado(self):
        # Dentro da tolerancia o aviso ainda pode estar a caminho; varrer agora
        # seria correr contra a propria fila e disparar o lote duas vezes.
        self.store["execucoes_ai_batch"].append(_lote("b1", "PENDENTE", 10))
        delay = MagicMock()

        self._rodar(delay)

        delay.assert_not_called()
        self.assertEqual(self._status("b1"), "PENDENTE")

    def test_broker_ainda_fora_devolve_o_lote_para_pendente(self):
        # Sem esta devolucao o lote ficaria preso em RODANDO sem ninguem
        # processando — exatamente o estado que a varredura existe para evitar.
        self.store["execucoes_ai_batch"].append(_lote("b1", "PENDENTE", 600))

        resultado = self._rodar(MagicMock(side_effect=OSError("recusou")))

        self.assertEqual(resultado["retomados"], [])
        self.assertEqual(self._status("b1"), "PENDENTE")

    def test_rodando_travado_e_encerrado_sem_reenfileirar(self):
        # Reenfileirar duplicaria itens e contaria o mesmo pedido duas vezes.
        self.store["execucoes_ai_batch"].append(
            _lote("b1", "RODANDO", 10_000, total=5, processados=2)
        )
        delay = MagicMock()

        resultado = self._rodar(delay)

        delay.assert_not_called()
        self.assertEqual(resultado["encerrados"], ["b1"])
        self.assertEqual(self._status("b1"), "ERRO")

    def test_rodando_completo_mas_nao_finalizado_vira_concluido(self):
        # Processou tudo e o ultimo incremento falhou: CONCLUIDO e mais fiel ao
        # que aconteceu do que marcar erro num lote que deu certo.
        self.store["execucoes_ai_batch"].append(
            _lote("b1", "RODANDO", 10_000, total=5, processados=5)
        )

        resultado = self._rodar()

        self.assertEqual(resultado["encerrados"], [])
        self.assertEqual(self._status("b1"), "CONCLUIDO")

    def test_rodando_recente_nao_e_interrompido(self):
        # Cada pedido e uma chamada de IA; um lote grande demora de verdade.
        self.store["execucoes_ai_batch"].append(
            _lote("b1", "RODANDO", 300, total=50, processados=4)
        )

        self._rodar()

        self.assertEqual(self._status("b1"), "RODANDO")


if __name__ == "__main__":
    unittest.main()
