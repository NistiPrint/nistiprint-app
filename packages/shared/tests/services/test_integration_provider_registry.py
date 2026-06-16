import unittest

from nistiprint_shared.services.integration_provider_registry import (
    get_provider_spec,
    normalize_provider_module_id,
)


class IntegrationProviderRegistryTest(unittest.TestCase):
    def test_normalize_provider_module_id_maps_shopee_variants(self):
        self.assertEqual(normalize_provider_module_id("shopee"), "shopee")
        self.assertEqual(normalize_provider_module_id("shopee_br"), "shopee")

    def test_get_provider_spec_returns_expected_secret_fields(self):
        shopee_spec = get_provider_spec("shopee_br")
        bling_spec = get_provider_spec("bling")

        self.assertEqual(
            [field.secret_kind for field in shopee_spec.app_profile_secret_fields],
            ["partner_id", "partner_key"],
        )
        self.assertEqual(
            [field.secret_kind for field in bling_spec.app_profile_secret_fields],
            ["client_id", "client_secret"],
        )
        self.assertTrue(bling_spec.supports_pkce)
        self.assertFalse(shopee_spec.supports_pkce)


if __name__ == "__main__":
    unittest.main()
