import base64
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.integration_secret_service import (
    IntegrationSecretService,
    SecretStorageError,
)


class IntegrationSecretServiceTest(unittest.TestCase):
    @patch("nistiprint_shared.services.integration_secret_service.supabase_db")
    def test_refresh_tokens_are_persisted_together_through_lease_rpc(self, db):
        service = IntegrationSecretService()
        db.rpc.return_value.execute.return_value.data = True
        with patch.object(service, "encrypt_secret", side_effect=[
            ("cipher-access", "nonce-access", "V1"),
            ("cipher-refresh", "nonce-refresh", "V1"),
        ]):
            service.persist_tokens_with_refresh_lease(
                "integration-7",
                {"access_token": "new-access", "refresh_token": "new-refresh"},
                "22222222-2222-4222-8222-222222222222",
            )

        db.rpc.assert_called_once_with("persistir_tokens_integracao_sob_lease", {
            "p_integration_id": "integration-7",
            "p_lease_token": "22222222-2222-4222-8222-222222222222",
            "p_access_token": {
                "encrypted_value": "cipher-access", "nonce": "nonce-access", "key_version": "V1",
            },
            "p_refresh_token": {
                "encrypted_value": "cipher-refresh", "nonce": "nonce-refresh", "key_version": "V1",
            },
            "p_schema_name": "public",
            "p_installation_patch": None,
        })

    @patch("nistiprint_shared.services.integration_secret_service.supabase_db")
    def test_refresh_rpc_receives_installation_patch_atomically(self, db):
        service = IntegrationSecretService()
        db.rpc.return_value.execute.return_value.data = True
        patch_data = {
            "config": {"shop_id": "456"},
            "credentials": {"shop_id": "456"},
            "expires_at": "2026-10-09T12:00:00+00:00",
            "last_refresh_attempt": "2026-10-09T11:00:00+00:00",
            "refresh_error": None,
        }
        with patch.object(service, "encrypt_secret", side_effect=[
            ("cipher-access", "nonce-access", "V1"),
            ("cipher-refresh", "nonce-refresh", "V1"),
        ]):
            service.persist_tokens_with_refresh_lease(
                "7", {"access_token": "new-access", "refresh_token": "new-refresh"},
                "22222222-2222-4222-8222-222222222222",
                installation_patch=patch_data,
            )

        self.assertEqual(db.rpc.call_args.args[1]["p_installation_patch"], patch_data)
    @patch("nistiprint_shared.services.integration_secret_service.supabase_db")
    def test_lost_refresh_lease_does_not_persist_returned_tokens(self, db):
        service = IntegrationSecretService()
        db.rpc.return_value.execute.return_value.data = False
        with patch.object(service, "encrypt_secret", return_value=("cipher", "nonce", "V1")):
            with self.assertRaises(SecretStorageError):
                service.persist_tokens_with_refresh_lease(
                    "integration-7", {"refresh_token": "stale-token"},
                    "22222222-2222-4222-8222-222222222222",
                )

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
