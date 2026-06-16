import unittest

from utils.order_timestamp_normalizer import build_order_timestamps, normalize_order_timestamp


class TestOrderTimestampNormalizer(unittest.TestCase):
    def test_normalizes_postgres_timestamptz_string(self):
        self.assertEqual(
            normalize_order_timestamp("2026-06-14 11:02:22-03"),
            "2026-06-14T11:02:22-03:00",
        )

    def test_normalizes_iso_with_offset(self):
        self.assertEqual(
            normalize_order_timestamp("2026-06-14T11:02:22-03:00"),
            "2026-06-14T11:02:22-03:00",
        )

    def test_normalizes_unix_string(self):
        self.assertEqual(
            normalize_order_timestamp("1781445742"),
            "2026-06-14T11:02:22-03:00",
        )

    def test_uses_snapshot_when_order_columns_are_missing(self):
        timestamps = build_order_timestamps(
            pedido={},
            snapshot={
                "logistics": {
                    "purchase_at": "2026-06-14T11:01:46-03:00",
                    "payment_at": "2026-06-14T11:02:22-03:00",
                }
            },
        )

        self.assertEqual(timestamps["compra"], "2026-06-14T11:01:46-03:00")
        self.assertEqual(timestamps["pagamento"], "2026-06-14T11:02:22-03:00")

    def test_endpoint_contract_fields_can_be_populated_from_direct_columns(self):
        timestamps = build_order_timestamps(
            pedido={
                "data_compra_marketplace": "2026-06-14 11:01:46-03",
                "data_pagamento_marketplace": "2026-06-14 11:02:22-03",
            }
        )
        response_fragment = {
            "data_compra_marketplace": timestamps["compra"],
            "data_pagamento_marketplace": timestamps["pagamento"],
            "datas": {
                "compra_marketplace": timestamps["compra"],
                "pagamento_marketplace": timestamps["pagamento"],
            },
        }

        self.assertEqual(response_fragment["data_compra_marketplace"], "2026-06-14T11:01:46-03:00")
        self.assertEqual(response_fragment["data_pagamento_marketplace"], "2026-06-14T11:02:22-03:00")
        self.assertEqual(response_fragment["datas"]["compra_marketplace"], "2026-06-14T11:01:46-03:00")
        self.assertEqual(response_fragment["datas"]["pagamento_marketplace"], "2026-06-14T11:02:22-03:00")


if __name__ == "__main__":
    unittest.main()
