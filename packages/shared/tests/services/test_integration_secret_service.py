import base64
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.integration_secret_service import (
    IntegrationSecretService,
    SecretStorageError,
)


class IntegrationSecretServiceTest(unittest.TestCase):
    def test_defaults_to_public_schema_for_postgrest_compatibility(self):
        service = IntegrationSecretService()

        self.assertEqual(service.schema_name, "public")

    @patch.dict(
        "os.environ",
        {
            "INTEGRATION_SECRETS_MASTER_KEY_V1": base64.b64encode(b"12345678901234567890123456789012").decode("ascii")
        },
        clear=False,
    )
    def test_encrypt_and_decrypt_round_trip(self):
        service = IntegrationSecretService()

        encrypted_value, nonce, key_version = service.encrypt_secret("super-secret")

        self.assertEqual(key_version, "V1")
        self.assertNotEqual(encrypted_value, "super-secret")
        self.assertEqual(
            service.decrypt_secret(encrypted_value, nonce, key_version),
            "super-secret",
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_master_key_raises_without_leaking_secret(self):
        service = IntegrationSecretService()

        with self.assertRaises(SecretStorageError) as ctx:
            service.encrypt_secret("super-secret")

        self.assertIn("INTEGRATION_SECRETS_MASTER_KEY_V1", str(ctx.exception))
        self.assertNotIn("super-secret", str(ctx.exception))

    @patch.dict(
        "os.environ",
        {
            "INTEGRATION_SECRETS_MASTER_KEY_V1": base64.b64encode(b"12345678901234567890123456789012").decode("ascii")
        },
        clear=False,
    )
    def test_decode_inline_secret_rejects_invalid_payload(self):
        service = IntegrationSecretService()

        with self.assertRaises(SecretStorageError):
            service.decode_inline_secret("invalid-payload")

    @patch("nistiprint_shared.services.integration_secret_service.supabase_db")
    def test_secret_presence_batch_selects_metadata_only(self, db):
        service = IntegrationSecretService()
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[
                {"owner_id": "11", "secret_kind": "access_token"},
                {"owner_id": "12", "secret_kind": "refresh_token"},
                {"owner_id": "99", "secret_kind": "access_token"},
            ]
        )
        db._ensure_client.return_value = True
        db.client.schema.return_value.table.return_value = query

        result = service.secret_kinds_for_owners(
            "installed_integration",
            [11, 12],
            ["access_token", "refresh_token"],
        )

        self.assertEqual(
            result,
            {"11": {"access_token"}, "12": {"refresh_token"}},
        )
        query.select.assert_called_once_with("owner_id, secret_kind")
        query.execute.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
