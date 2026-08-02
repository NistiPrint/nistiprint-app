"""Backoff e horizonte do enriquecimento de referencia ERP.

O pedido de ingest direto nasce sem `erp_order_id` e so ganha referencia quando
o Bling importa o pedido do marketplace. Medido em 02/08/2026 (apenas itens
posteriores ao restart do beat, para nao medir o represamento):

    n=22   menor=1min   mediana=49min   p90=90min   maior=97min

A politica anterior desistia em ~20 minutos — menos da metade da mediana. Os 64
itens que terminaram em `failed` nao eram pedidos ausentes do Bling: eram
pedidos que ainda nao tinham chegado quando o sistema parou de perguntar.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import order_erp_reference_service as svc


class TestBackoff(unittest.TestCase):
    def _minutos_ate(self, iso: str) -> float:
        alvo = datetime.fromisoformat(iso)
        return (alvo - datetime.now(timezone.utc)).total_seconds() / 60

    def test_primeiras_tentativas_sao_rapidas(self):
        """Uma minoria resolve em poucos minutos; vale perguntar cedo."""
        self.assertLessEqual(self._minutos_ate(svc._proxima_tentativa_iso(0)), 1.5)
        self.assertLessEqual(self._minutos_ate(svc._proxima_tentativa_iso(1)), 2.5)

    def test_espacamento_cresce(self):
        esperas = [self._minutos_ate(svc._proxima_tentativa_iso(n)) for n in range(8)]
        self.assertEqual(esperas, sorted(esperas), "o backoff deve ser monotonico")
        self.assertGreater(esperas[-1], esperas[0])

    def test_cobre_a_mediana_real_de_49min(self):
        """A soma das primeiras esperas tem de passar de 49 minutos."""
        acumulado = sum(svc.BACKOFF_MINUTOS[:6])
        self.assertGreaterEqual(
            acumulado, 49, "o backoff desiste antes da mediana observada"
        )

    def test_cobre_o_p90_de_90min(self):
        acumulado = sum(svc.BACKOFF_MINUTOS)
        self.assertGreaterEqual(acumulado, 90)

    def test_indice_acima_da_tabela_usa_o_maior_intervalo(self):
        maior = svc.BACKOFF_MINUTOS[-1]
        self.assertAlmostEqual(
            self._minutos_ate(svc._proxima_tentativa_iso(99)), maior, delta=0.5
        )


class TestHorizonte(unittest.TestCase):
    def test_item_recente_nao_desiste(self):
        recente = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertFalse(svc._excedeu_horizonte(recente))

    def test_item_alem_do_horizonte_desiste(self):
        antigo = (
            datetime.now(timezone.utc) - timedelta(hours=svc.HORIZONTE_HORAS + 1)
        ).isoformat()
        self.assertTrue(svc._excedeu_horizonte(antigo))

    def test_horizonte_cobre_o_maior_tempo_observado(self):
        """97 minutos foi o pior caso medido; 24h da folga de ordem de grandeza."""
        self.assertGreaterEqual(svc.HORIZONTE_HORAS * 60, 97 * 5)

    def test_created_at_ausente_nao_desiste(self):
        self.assertFalse(svc._excedeu_horizonte(None))

    def test_created_at_ilegivel_nao_desiste(self):
        """Na duvida, continua tentando: desistir e o caminho sem volta."""
        self.assertFalse(svc._excedeu_horizonte("ontem de tarde"))

    def test_naive_datetime_e_tratado_como_utc(self):
        antigo = (
            datetime.now(timezone.utc) - timedelta(hours=svc.HORIZONTE_HORAS + 2)
        ).replace(tzinfo=None).isoformat()
        self.assertTrue(svc._excedeu_horizonte(antigo))


class TestIntegracaoComAFila(unittest.TestCase):
    """A desistencia passa a ser por idade, nao por contagem de tentativas."""

    class _Tabela:
        def __init__(self, data):
            self.updates = []
            self._data = data
            self._payload = None

        def select(self, *a, **k):
            return self

        def eq(self, coluna, valor):
            if coluna == "id" and self._payload is not None:
                self.updates.append((valor, self._payload))
                self._payload = None
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
            self._payload = payload
            return self

        def execute(self):
            return MagicMock(data=self._data)

    def _rodar(self, rows, situacoes):
        tabela = self._Tabela(rows)
        batch = {
            "ready": [],
            "blocked": [
                {"pedido_id": r["pedido_id"], "status": "pending", "message": "nao achou"}
                for r in rows
            ],
        }
        with patch.object(svc, "supabase_db") as db, patch.object(
            svc, "_situacoes_por_pedido", return_value=situacoes
        ), patch.object(svc, "_resolve_pending_references_in_batch", return_value=batch):
            db.table.return_value = tabela
            resultado = svc.reconcile_pending_erp_references.__wrapped__.__wrapped__(limit=50)
        return resultado, tabela.updates

    def test_muitas_tentativas_mas_recente_continua_tentando(self):
        """O caso exato dos 64 falsos negativos: tentou muito, mas e novo."""
        recente = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
        rows = [{"id": 1, "pedido_id": 100, "attempts": 30, "created_at": recente}]
        resultado, updates = self._rodar(rows, {100: 2})

        self.assertEqual(resultado["exhausted"], 0)
        self.assertEqual(updates[0][1]["status"], "pending")
        self.assertIsNotNone(updates[0][1]["next_attempt_after"])

    def test_poucas_tentativas_mas_antigo_desiste(self):
        antigo = (
            datetime.now(timezone.utc) - timedelta(hours=svc.HORIZONTE_HORAS + 1)
        ).isoformat()
        rows = [{"id": 1, "pedido_id": 100, "attempts": 2, "created_at": antigo}]
        resultado, updates = self._rodar(rows, {100: 2})

        self.assertEqual(resultado["exhausted"], 1)
        self.assertEqual(updates[0][1]["status"], "failed")
        self.assertIsNone(updates[0][1]["next_attempt_after"])


if __name__ == "__main__":
    unittest.main()
