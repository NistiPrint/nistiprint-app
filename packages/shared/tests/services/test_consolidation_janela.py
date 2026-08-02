"""Janela de agrupamento: deslizante, mas com teto.

A janela reabre a cada pedido novo, o que e desejado — pedidos do mesmo grupo
continuam entrando. Sem teto, porem, um fluxo continuo empurra o vencimento
indefinidamente e o rascunho nunca fecha. Foi assim que a demanda
`DEM-20260710065646-27` ficou 6 dias aberta e acumulou 1.038 pedidos, virando
uma fila em vez de uma demanda executavel.
"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


class _Regra:
    def __init__(self, janela_horas=4):
        self.janela_agrupamento_horas = janela_horas
        self.agrupar_por_produto = False
        self.agrupar_por_miolo = False
        self.agrupar_por_data_entrega = True


class TestTetoDaJanela(unittest.TestCase):
    def setUp(self):
        with patch(
            "nistiprint_shared.services.consolidation_service.supabase_db",
            MagicMock(),
        ):
            from nistiprint_shared.services.consolidation_service import (
                ConsolidationService,
            )

            self.service = ConsolidationService()

    def _agora(self):
        from nistiprint_shared.utils.date_utils import get_now

        return get_now()

    def test_teto_fecha_rascunho_antigo(self):
        """Rascunho criado ha 3 dias nao pode ser estendido para amanha."""
        criado = self._agora() - timedelta(days=3)
        teto = self.service._teto_da_janela(
            {"id": 1, "created_at": criado.isoformat()}, _Regra(janela_horas=4)
        )
        self.assertIsNotNone(teto)
        self.assertLess(teto, self._agora())

    def test_rascunho_recente_ainda_tem_folga(self):
        criado = self._agora() - timedelta(hours=1)
        teto = self.service._teto_da_janela(
            {"id": 1, "created_at": criado.isoformat()}, _Regra(janela_horas=4)
        )
        self.assertGreater(teto, self._agora())

    def test_janela_configurada_maior_que_o_teto_vence(self):
        """Intencao explicita do operador ganha do default."""
        criado = self._agora() - timedelta(hours=30)
        teto = self.service._teto_da_janela(
            {"id": 1, "created_at": criado.isoformat()}, _Regra(janela_horas=72)
        )
        self.assertGreater(teto, self._agora())

    def test_created_at_ausente_nao_quebra(self):
        self.assertIsNone(self.service._teto_da_janela({"id": 1}, _Regra()))

    def test_created_at_ilegivel_nao_quebra(self):
        self.assertIsNone(
            self.service._teto_da_janela(
                {"id": 1, "created_at": "nao é uma data"}, _Regra()
            )
        )

    def test_cenario_da_demanda_de_1038_pedidos(self):
        """Reproduz o caso real: 6 dias de janela deslizante ininterrupta."""
        criado = datetime.fromisoformat("2026-07-10T06:56:46+00:00")
        with patch(
            "nistiprint_shared.services.consolidation_service.get_now",
            return_value=datetime.fromisoformat("2026-07-16T19:51:46+00:00"),
        ):
            teto = self.service._teto_da_janela(
                {"id": 23, "created_at": criado.isoformat()}, _Regra(janela_horas=4)
            )
        # Teto em 11/07, muito antes do vencimento real observado (16/07).
        self.assertEqual(teto.date().isoformat(), "2026-07-11")


class TestBuscaRascunhoSimetrica(unittest.TestCase):
    """A busca aplica o que a chave declara."""

    def setUp(self):
        with patch(
            "nistiprint_shared.services.consolidation_service.supabase_db",
            MagicMock(),
        ):
            from nistiprint_shared.services.consolidation_service import (
                ConsolidationService,
            )

            self.service = ConsolidationService()

    def test_sem_canal_nao_busca(self):
        """`.eq(coluna, None)` nunca casa: melhor dizer que nao ha compativel."""
        from nistiprint_shared.services.consolidation_service import ConsolidacaoChave

        chave = ConsolidacaoChave(canal_venda_id=None, modalidade="STANDARD")
        self.assertIsNone(self.service._buscar_rascunho_compativel(chave))

    def test_data_entrega_entra_no_filtro(self):
        from nistiprint_shared.services.consolidation_service import ConsolidacaoChave

        query = MagicMock()
        query.select.return_value = query
        for metodo in ("eq", "gt", "order", "limit"):
            getattr(query, metodo).return_value = query
        query.execute.return_value = MagicMock(data=[])
        self.service.demandas_table = query

        chave = ConsolidacaoChave(
            canal_venda_id=27, modalidade="EXPRESS", data_entrega="2026-08-02"
        )
        self.service._buscar_rascunho_compativel(chave)

        filtros = {c.args[0]: c.args[1] for c in query.eq.call_args_list}
        self.assertEqual(filtros.get("data_entrega"), "2026-08-02")
        self.assertEqual(filtros.get("canal_venda_id"), 27)
        self.assertEqual(filtros.get("modalidade_logistica"), "EXPRESS")


if __name__ == "__main__":
    unittest.main()
