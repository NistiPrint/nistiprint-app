"""O modo de ingest que governa um pedido e o congelado nele, nao o do vinculo.

Existe para tornar possivel migrar uma conta de `erp_bling` para
`marketplace_direct`. Sem o congelamento, virar a chave do vinculo troca a
autoridade retroativamente: um pedido em transito que so o ERP acompanha perde
sua fonte no meio do ciclo e congela na ultima situacao projetada.
"""
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.canonical_order_repository import (
    CanonicalOrderRepository,
)


def _supabase_com_pedido(pedido_row):
    fake = MagicMock()
    execute = MagicMock()
    execute.data = [pedido_row] if pedido_row else []
    (
        fake.table.return_value.select.return_value.eq.return_value.limit.return_value.execute
    ).return_value = execute
    return fake


class ModoCongeladoNoPedidoTest(unittest.TestCase):
    def setUp(self):
        self.repo = CanonicalOrderRepository()

    def _resolver(self, pedido_row, link_row):
        with patch(
            "nistiprint_shared.services.canonical_order_repository.supabase_db",
            _supabase_com_pedido(pedido_row),
        ), patch.object(
            self.repo, "resolve_erp_marketplace_link", return_value=link_row
        ):
            return self.repo.resolve_ingest_origin_mode_for_order(1)

    def test_pedido_congelado_vence_o_vinculo_ja_migrado(self):
        modo = self._resolver(
            {
                "erp_integration_id": 1,
                "erp_store_id": "203753446",
                "marketplace_module_id": "mercadolivre",
                "ingest_origin_mode": "erp_bling",
            },
            {"ingest_origin_mode": "marketplace_direct"},
        )
        self.assertEqual(modo, "erp_bling")

    def test_pedido_antigo_sem_modo_cai_no_vinculo(self):
        modo = self._resolver(
            {
                "erp_integration_id": 1,
                "erp_store_id": "203753446",
                "marketplace_module_id": "mercadolivre",
                "ingest_origin_mode": None,
            },
            {"ingest_origin_mode": "marketplace_direct"},
        )
        self.assertEqual(modo, "marketplace_direct")

    def test_pedido_novo_nasce_sob_o_modo_novo(self):
        modo = self._resolver(
            {
                "erp_integration_id": 1,
                "erp_store_id": "203753446",
                "marketplace_module_id": "mercadolivre",
                "ingest_origin_mode": "marketplace_direct",
            },
            {"ingest_origin_mode": "marketplace_direct"},
        )
        self.assertEqual(modo, "marketplace_direct")

    def test_sem_modo_e_sem_vinculo_pedido_de_marketplace_preserva(self):
        """Duvida resolve a favor de preservar: None nao e autoritativo."""
        modo = self._resolver(
            {
                "erp_integration_id": None,
                "erp_store_id": None,
                "marketplace_module_id": "mercadolivre",
                "ingest_origin_mode": None,
            },
            None,
        )
        self.assertIsNone(modo)

    def test_pedido_puramente_erp_segue_com_o_bling(self):
        modo = self._resolver(
            {
                "erp_integration_id": 1,
                "erp_store_id": "999",
                "marketplace_module_id": None,
                "ingest_origin_mode": None,
            },
            None,
        )
        self.assertEqual(modo, "erp_bling")
