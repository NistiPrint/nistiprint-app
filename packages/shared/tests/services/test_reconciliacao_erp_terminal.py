"""Fila de reconciliacao ERP: terminal nao e falha.

O Bling so importa pedido que se concretizou. Um pedido cancelado ou devolvido
no marketplace nunca chega la — e nao precisa: nao sera faturado nem impresso.

Antes, esses itens gastavam 20 tentativas cada e terminavam em `failed`, no meio
das falhas de verdade. Medido em 02/08/2026: dos 128 itens esgotados, 64 eram
devolucoes. Metade da fila de falhas nao era falha, e isso escondia as que eram.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import order_erp_reference_service as svc


def agora_menos(minutos=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()


class _Tabela:
    """Espia as chamadas de update por id."""

    def __init__(self, select_data=None):
        self.updates = []
        self._select_data = select_data or []
        self._pending_update = None

    def select(self, *a, **k):
        return self

    def eq(self, coluna, valor):
        if coluna == "id" and self._pending_update is not None:
            self.updates.append((valor, self._pending_update))
            self._pending_update = None
        return self

    def or_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def execute(self):
        return MagicMock(data=self._select_data)


class TestPoliticaTerminal(unittest.TestCase):
    def _rodar(self, rows, situacoes, batch=None):
        tabela = _Tabela(select_data=rows)
        batch = batch or {"ready": [], "blocked": []}
        with patch.object(svc, "supabase_db") as db, patch.object(
            svc, "_situacoes_por_pedido", return_value=situacoes
        ), patch.object(svc, "_resolve_pending_references_in_batch", return_value=batch):
            db.table.return_value = tabela
            resultado = svc.reconcile_pending_erp_references.__wrapped__.__wrapped__(limit=50)
        return resultado, tabela.updates

    def test_devolvido_encerra_sem_gastar_tentativa(self):
        rows = [{"id": 1, "pedido_id": 100, "attempts": 3, "created_at": agora_menos(10)}]
        resultado, updates = self._rodar(rows, {100: 8})  # 8 = Devolvido

        self.assertEqual(resultado["skipped_terminal"], 1)
        self.assertEqual(len(updates), 1)
        _, payload = updates[0]
        self.assertEqual(payload["status"], "skipped_terminal")
        # O ponto: nao incrementa tentativa, porque nao ha o que tentar.
        self.assertNotIn("attempts", payload)

    def test_cancelado_tambem_encerra(self):
        resultado, updates = self._rodar(
            [{"id": 1, "pedido_id": 100, "attempts": 0, "created_at": agora_menos(10)}],
            {100: 7},
        )
        self.assertEqual(resultado["skipped_terminal"], 1)
        self.assertEqual(updates[0][1]["status"], "skipped_terminal")

    def test_pedido_ativo_continua_tentando(self):
        rows = [{"id": 1, "pedido_id": 100, "attempts": 3, "created_at": agora_menos(10)}]
        batch = {
            "ready": [],
            "blocked": [{"pedido_id": 100, "status": "pending", "message": "nao achou"}],
        }
        resultado, updates = self._rodar(rows, {100: 2}, batch)  # 2 = Em Andamento

        self.assertEqual(resultado["skipped_terminal"], 0)
        self.assertEqual(updates[0][1]["status"], "pending")
        self.assertEqual(updates[0][1]["attempts"], 4)

    def test_resolvido_nao_recebe_update(self):
        rows = [{"id": 1, "pedido_id": 100, "attempts": 3, "created_at": agora_menos(10)}]
        batch = {"ready": [{"pedido_id": 100}], "blocked": []}
        resultado, updates = self._rodar(rows, {100: 2}, batch)

        self.assertEqual(resultado["applied"], 1)
        self.assertEqual(updates, [])

    def test_lote_misto_separa_os_tres_destinos(self):
        antigo = agora_menos(60 * (svc.HORIZONTE_HORAS + 1))
        rows = [
            {"id": 1, "pedido_id": 100, "attempts": 0, "created_at": agora_menos(5)},   # devolvido
            {"id": 2, "pedido_id": 200, "attempts": 5, "created_at": antigo},           # ativo, velho
            {"id": 3, "pedido_id": 300, "attempts": 0, "created_at": agora_menos(5)},   # resolvido
        ]
        batch = {
            "ready": [{"pedido_id": 300}],
            "blocked": [{"pedido_id": 200, "status": "pending", "message": "nao achou"}],
        }
        resultado, updates = self._rodar(rows, {100: 8, 200: 2, 300: 2}, batch)

        self.assertEqual(resultado["skipped_terminal"], 1)
        self.assertEqual(resultado["exhausted"], 1)
        self.assertEqual(resultado["applied"], 1)
        por_id = dict(updates)
        self.assertEqual(por_id[1]["status"], "skipped_terminal")
        self.assertEqual(por_id[2]["status"], "failed")
        self.assertNotIn(3, por_id)

    def test_terminal_nao_chega_a_consultar_o_bling(self):
        """Economia real: pedido terminal nao gasta chamada de API."""
        rows = [{"id": 1, "pedido_id": 100, "attempts": 0, "created_at": agora_menos(10)}]
        tabela = _Tabela(select_data=rows)
        with patch.object(svc, "supabase_db") as db, patch.object(
            svc, "_situacoes_por_pedido", return_value={100: 8}
        ), patch.object(
            svc, "_resolve_pending_references_in_batch", return_value={"ready": [], "blocked": []}
        ) as resolver:
            db.table.return_value = tabela
            svc.reconcile_pending_erp_references.__wrapped__.__wrapped__(limit=50)

        # Chamado com lista vazia: nenhum pedido ativo sobrou no lote.
        resolver.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
