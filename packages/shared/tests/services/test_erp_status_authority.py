"""Guarda de autoridade: o Bling nao dita situacao de pedido que nao e dele.

Estes testes existem porque a guarda anterior era uma lista literal de
marketplaces comparada com `pedidos.origem`. Ela falhava nos dois sentidos e o
sistema nao tinha como perceber:

- deixava passar: os valores reais de `origem` em producao sao
  `AMAZONFBA_CLASSIC`, `TIKTOKSHOP`, `MAGAZINELUIZA`, `LOJAINTEGRADA` e `KWAI`,
  e a lista dizia `AMAZON` e `TIKTOK`;
- bloqueava demais: um pedido Shopee ingerido via `erp_bling` tem o Bling como
  autoridade legitima, e a lista o barrava igual.

A pergunta certa nao e "de que marketplace veio", e sim "quem governa o ciclo de
vida deste vinculo" — ou seja, `ingest_origin_mode`.
"""
import unittest
from unittest.mock import patch

from nistiprint_shared.services.canonical_order_repository import (
    CanonicalOrderRepository,
)


class TestErpStatusAuthority(unittest.TestCase):
    def setUp(self):
        self.repo = CanonicalOrderRepository()

    # ------------------------------------------------------------------ #
    # Resolucao a partir de um pedido existente
    # ------------------------------------------------------------------ #

    def _com_pedido(self, pedido_row, link_row):
        """Injeta o pedido e o vinculo que o repositorio enxergaria."""
        return (
            patch.object(
                self.repo,
                "resolve_ingest_origin_mode_for_order",
                wraps=self.repo.resolve_ingest_origin_mode_for_order,
            ),
            patch.object(self.repo, "resolve_erp_marketplace_link", return_value=link_row),
            patch(
                "nistiprint_shared.services.canonical_order_repository.supabase_db"
            ),
        )

    def test_marketplace_direct_bloqueia_projecao_do_erp(self):
        with patch.object(
            self.repo,
            "resolve_ingest_origin_mode_for_order",
            return_value="marketplace_direct",
        ):
            self.assertFalse(self.repo.erp_can_project_status(123))

    def test_erp_bling_permite_projecao_do_erp(self):
        with patch.object(
            self.repo,
            "resolve_ingest_origin_mode_for_order",
            return_value="erp_bling",
        ):
            self.assertTrue(self.repo.erp_can_project_status(123))

    def test_vinculo_irresolvivel_preserva_situacao(self):
        """Na duvida, nao sobrescreve: preservar e reversivel, sobrescrever nao."""
        with patch.object(
            self.repo, "resolve_ingest_origin_mode_for_order", return_value=None
        ):
            self.assertFalse(self.repo.erp_can_project_status(123))

    # ------------------------------------------------------------------ #
    # Os canais que a lista literal deixava passar
    # ------------------------------------------------------------------ #

    def test_canais_que_a_lista_literal_nao_cobria(self):
        """`AMAZONFBA_CLASSIC` e `TIKTOKSHOP` nunca casaram com `AMAZON`/`TIKTOK`.

        Sob `marketplace_direct` os cinco devem ser bloqueados igualmente — a
        decisao nao olha mais para o nome do canal.
        """
        for modulo in (
            "amazonfba_classic",
            "tiktokshop",
            "magazineluiza",
            "lojaintegrada",
            "kwai",
        ):
            with self.subTest(modulo=modulo):
                with patch.object(
                    self.repo,
                    "resolve_erp_marketplace_link",
                    return_value={
                        "marketplace_module_id": modulo,
                        "ingest_origin_mode": "marketplace_direct",
                    },
                ):
                    self.assertFalse(
                        self.repo.erp_can_project_status_for_store(1, "204047801")
                    )

    def test_shopee_via_erp_bling_nao_e_bloqueado(self):
        """A lista literal barrava este caso, que e legitimo."""
        with patch.object(
            self.repo,
            "resolve_erp_marketplace_link",
            return_value={
                "marketplace_module_id": "shopee",
                "ingest_origin_mode": "erp_bling",
            },
        ):
            self.assertTrue(self.repo.erp_can_project_status_for_store(1, "204047801"))

    # ------------------------------------------------------------------ #
    # Resolucao sem pedido_id (sincronizacoes que montam payload antes)
    # ------------------------------------------------------------------ #

    def test_sem_vinculo_e_com_identidade_de_marketplace_preserva(self):
        with patch.object(self.repo, "resolve_erp_marketplace_link", return_value=None):
            self.assertFalse(
                self.repo.erp_can_project_status_for_store(
                    1, "999", has_marketplace_identity=True
                )
            )

    def test_sem_vinculo_e_pedido_puramente_erp_segue_com_bling(self):
        """Pedido que nasce no Bling e nao tem marketplace: o Bling manda nele."""
        with patch.object(self.repo, "resolve_erp_marketplace_link", return_value=None):
            self.assertTrue(
                self.repo.erp_can_project_status_for_store(
                    1, "999", has_marketplace_identity=False
                )
            )


if __name__ == "__main__":
    unittest.main()
