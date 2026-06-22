import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.token_manager.firebase_projection import (
    BlingFirebaseProjectionService,
)


class BlingFirebaseProjectionServiceTest(unittest.TestCase):
    def test_build_payload_preserves_expected_shape(self):
        service = BlingFirebaseProjectionService()
        installation = {
            "id": 7,
            "module_id": "bling",
            "instance_name": "Bling Principal",
            "config": {"cnpj": "12345678000199", "company_id": "9988"},
            "credentials": {"expires_in": 3600},
            "expires_at": datetime.now(timezone.utc).isoformat(),
            "refresh_error": None,
        }
        context = MagicMock()
        context.config = installation["config"]
        context.credentials = installation["credentials"]
        context.installation_secrets = {
            "access_token": "access-123",
            "refresh_token": "refresh-123",
        }

        with patch(
            "nistiprint_shared.services.token_manager.firebase_projection.credential_resolver_service.resolve_for_installation",
            return_value=context,
        ):
            payload = service.build_payload(installation)

        self.assertEqual(payload["cnpj"], "12345678000199")
        self.assertEqual(payload["account_name"], "Bling Principal")
        self.assertEqual(payload["company_id"], "9988")
        self.assertEqual(payload["access_token"], "access-123")
        self.assertEqual(payload["refresh_token"], "refresh-123")
        self.assertEqual(payload["token_expires_in"], 3600)
        self.assertIn("updated_at", payload)
        self.assertIn("last_token_update_utc", payload)
        self.assertIn("last_token_update_error", payload)

    def test_publish_installation_uses_existing_firebase_doc_id(self):
        service = BlingFirebaseProjectionService()
        installation = {
            "id": 7,
            "module_id": "bling",
            "instance_name": "Bling Principal",
            "config": {"cnpj": "12345678000199", "firebase_doc_id": "doc-abc"},
        }
        fake_doc = MagicMock()
        fake_collection = MagicMock()
        fake_collection.document.return_value = fake_doc

        with patch.object(service, "build_payload", return_value={"ok": True}), patch.object(
            service,
            "_get_collection",
            return_value=fake_collection,
        ):
            result = service.publish_installation(installation)

        fake_collection.document.assert_called_once_with("doc-abc")
        fake_doc.set.assert_called_once_with({"ok": True}, merge=True)
        self.assertEqual(result["doc_id"], "doc-abc")


if __name__ == "__main__":
    unittest.main()
