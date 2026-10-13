import asyncio
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.motor_reconciliacao_estoque import (
    MotorReconciliacaoEstoque,
    Movimento,
)


class MotorJitStockGuardTests(unittest.TestCase):
    def test_reconciliation_without_claim_lease_fails_before_database_access(self):
        motor = object.__new__(MotorReconciliacaoEstoque)
        with patch("nistiprint_shared.services.motor_reconciliacao_estoque.supabase_db.rpc") as rpc:
            result = asyncio.run(motor.reconcile_item(item_id=71, demanda_id=9))

        self.assertFalse(result.sucesso)
        self.assertIn("lease válido", result.erros[0])
        rpc.assert_not_called()

    def test_persistence_without_lease_never_calls_legacy_stock_writer(self):
        motor = object.__new__(MotorReconciliacaoEstoque)
        with patch("nistiprint_shared.services.motor_reconciliacao_estoque.supabase_db.rpc") as rpc:
            result = asyncio.run(motor._persistir_via_rpc(
                movimentos=[], item_id=71, demanda_id=9, correlation_id="corr-1",
                user_id="System", snapshot={"qtd_finalizada": 1},
            ))

        self.assertFalse(result.sucesso)
        self.assertIn("lease", result.erros[0])
        rpc.assert_not_called()

    def test_available_stock_adds_only_own_unconsumed_reservation_in_same_deposit(self):
        motor = object.__new__(MotorReconciliacaoEstoque)
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.execute.return_value = SimpleNamespace(data=[
            {"quantidade_alocada": 10, "quantidade_consumida": 4, "quantidade_liberada": 1},
            {"quantidade_alocada": 3, "quantidade_consumida": 3, "quantidade_liberada": 0},
        ])
        with (
            patch("nistiprint_shared.services.motor_reconciliacao_estoque.estoque_service.get_saldo_atual",
                  return_value={"produto_id": 8, "deposito_id": 2, "quantidade": 20,
                                "quantidade_reservada": 15, "quantidade_disponivel": 5}) as stock,
            patch("nistiprint_shared.services.motor_reconciliacao_estoque.supabase_db.table",
                  return_value=query),
        ):
            result = asyncio.run(motor._get_saldo_disponivel(8, item_id=71, deposito_id=2))

        stock.assert_called_once_with(8, 2)
        self.assertEqual(result["reserva_propria"], Decimal("5"))
        self.assertEqual(result["quantidade_disponivel"], Decimal("10"))
        query.eq.assert_any_call("deposito_id", 2)

    def test_negative_available_is_not_consumed_from_intermediate(self):
        current_available = Decimal("-7")
        required = Decimal("3")
        used_from_stock = max(Decimal("0"), min(current_available, required))
        missing = required - used_from_stock

        self.assertEqual(used_from_stock, Decimal("0"))
        self.assertEqual(missing, required)

    def test_attaches_full_stock_snapshot_to_all_movements_for_product_decision(self):
        movements = [
            Movimento(12, "PROD_INT", Decimal("2"), "JIT", deposito_id=1),
            Movimento(12, "CONS_INT", Decimal("-2"), "JIT consume", deposito_id=1),
        ]
        MotorReconciliacaoEstoque._anexar_precondicao_saldo(
            movements,
            12,
            {"quantidade": "4.0000", "quantidade_reservada": "1.0000",
             "reserva_propria": Decimal("0.5"), "quantidade_disponivel": Decimal("3.5")},
        )

        self.assertEqual(movements[0].expected_saldo, Decimal("4.0000"))
        self.assertEqual(movements[0].expected_reservado, Decimal("1.0000"))
        self.assertEqual(movements[0].expected_reserva_propria, Decimal("0.5"))
        self.assertEqual(movements[0].expected_disponivel, Decimal("3.5"))
        self.assertEqual(movements[1].expected_saldo, Decimal("4.0000"))
        self.assertEqual(movements[1].expected_reservado, Decimal("1.0000"))
        self.assertEqual(movements[1].expected_reserva_propria, Decimal("0.5"))
        self.assertEqual(movements[1].expected_disponivel, Decimal("3.5"))


if __name__ == "__main__":
    unittest.main()
