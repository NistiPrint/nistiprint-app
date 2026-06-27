import unittest
from unittest.mock import MagicMock, patch

from postgrest.exceptions import APIError

from nistiprint_shared.services import canonical_order_repository as repository_module


class TestCanonicalOrderRepository(unittest.TestCase):
    def test_upsert_normalizes_identity_and_calls_atomic_rpc(self):
        rpc_query = MagicMock()
        rpc_query.execute.return_value.data = 42
        service = repository_module.CanonicalOrderRepository()

        with patch.object(repository_module.supabase_db, "rpc", return_value=rpc_query) as rpc:
            pedido_id = service.upsert(
                {
                    "marketplace_module_id": "Mercado-Livre",
                    "marketplace_order_id": " 200001 ",
                    "total_pedido": 10,
                },
                snapshot={"customer": {"name": "Maria"}},
                refs=[],
            )

        self.assertEqual(pedido_id, 42)
        params = rpc.call_args.args[1]
        self.assertEqual(params["p_order"]["marketplace_module_id"], "mercadolivre")
        self.assertEqual(params["p_order"]["marketplace_order_id"], "200001")
        self.assertEqual(params["p_snapshot"]["customer"]["name"], "Maria")

    def test_apply_marketplace_event_calls_atomic_lifecycle_rpc(self):
        rpc_query = MagicMock()
        rpc_query.execute.return_value.data = {
            "pedido_id": 42,
            "decision": "applied",
            "situacao_pedido_id": 5,
        }
        service = repository_module.CanonicalOrderRepository()

        with patch.object(repository_module.supabase_db, "rpc", return_value=rpc_query) as rpc:
            result = service.apply_marketplace_event(
                {
                    "marketplace_module_id": "Shopee",
                    "marketplace_order_id": " SN123 ",
                },
                lifecycle_event={
                    "lifecycle_stage": "shipped",
                    "target_situacao_pedido_id": 5,
                },
                projection_enabled=True,
            )

        self.assertEqual(result["pedido_id"], 42)
        self.assertEqual(rpc.call_args.args[0], "apply_marketplace_order_event")
        params = rpc.call_args.args[1]
        self.assertEqual(params["p_order"]["marketplace_module_id"], "shopee")
        self.assertEqual(params["p_order"]["marketplace_order_id"], "SN123")
        self.assertTrue(params["p_projection_enabled"])

    def test_upsert_rejects_incomplete_identity(self):
        service = repository_module.CanonicalOrderRepository()
        with self.assertRaises(repository_module.CanonicalOrderIdentityError):
            service.upsert({"marketplace_module_id": "shopee"})

    def test_upsert_retries_after_duplicate_pedido_bling_id_and_corrects_identity(self):
        duplicate = APIError({
            "message": 'duplicate key value violates unique constraint "ux_pedidos_pedido_bling_id"',
            "code": "23505",
            "hint": None,
            "details": 'Key (pedido_bling_id)=(24090) already exists. constraint ux_pedidos_pedido_bling_id',
        })
        first_query = MagicMock()
        first_query.execute.side_effect = duplicate
        second_query = MagicMock()
        second_query.execute.return_value.data = 55
        find_query = MagicMock()
        find_query.select.return_value = find_query
        find_query.eq.return_value = find_query
        find_query.limit.return_value = find_query
        find_query.execute.return_value.data = [
            {
                "id": 91,
                "marketplace_module_id": "mercadolivre",
                "marketplace_order_id": "OLD-ORDER",
            }
        ]
        correct_query = MagicMock()
        correct_query.execute.return_value.data = 91

        rpc_calls = [first_query, correct_query, second_query]
        service = repository_module.CanonicalOrderRepository()

        def rpc_side_effect(name, params):
            return rpc_calls.pop(0)

        with patch.object(
            repository_module.supabase_db, "rpc", side_effect=rpc_side_effect
        ) as rpc, patch.object(
            repository_module.supabase_db, "table", return_value=find_query
        ) as table:
            pedido_id = service.upsert(
                {
                    "marketplace_module_id": "mercadolivre",
                    "marketplace_order_id": "2000016654182190",
                    "pedido_bling_id": 24090,
                }
            )

        self.assertEqual(pedido_id, 55)
        self.assertEqual(rpc.call_args_list[1].args[0], "correct_canonical_order_identity")
        correction_params = rpc.call_args_list[1].args[1]
        self.assertEqual(correction_params["p_pedido_id"], 91)
        self.assertEqual(correction_params["p_marketplace_order_id"], "2000016654182190")
        table.assert_called_with("pedidos")


if __name__ == "__main__":
    unittest.main()

