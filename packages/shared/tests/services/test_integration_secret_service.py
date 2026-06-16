import base64
import unittest
from unittest.mock import patch

from nistiprint_shared.services.integration_secret_service import (
    IntegrationSecretService,
    SecretStorageError,
)


class IntegrationSecretServiceTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
