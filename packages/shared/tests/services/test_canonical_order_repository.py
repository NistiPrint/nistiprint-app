import unittest
from unittest.mock import MagicMock, patch

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

    def test_upsert_rejects_incomplete_identity(self):
        service = repository_module.CanonicalOrderRepository()
        with self.assertRaises(repository_module.CanonicalOrderIdentityError):
            service.upsert({"marketplace_module_id": "shopee"})


if __name__ == "__main__":
    unittest.main()

