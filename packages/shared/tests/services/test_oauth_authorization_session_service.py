import base64
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from nistiprint_shared.services.oauth_authorization_session_service import (
    OAuthAuthorizationSessionService,
    OAuthSessionError,
)


class _FakeTable:
    def __init__(self):
        self.rows = []
        self.filters = {}
        self.limit_value = None
        self.pending_update = None

    def insert(self, payload):
        row = dict(payload)
        row["id"] = row.get("id") or str(len(self.rows) + 1)
        self.rows.append(row)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[row]))

    def select(self, *_args):
        self.filters = {}
        self.limit_value = None
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def update(self, payload):
        self.pending_update = payload
        return self

    def execute(self):
        rows = [
            row for row in self.rows if all(row.get(key) == value for key, value in self.filters.items())
        ]
        if self.pending_update is not None:
            for row in rows:
                row.update(self.pending_update)
            payload = self.pending_update
            self.pending_update = None
            return SimpleNamespace(data=[payload])
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return SimpleNamespace(data=rows)


class OAuthAuthorizationSessionServiceTest(unittest.TestCase):
    def setUp(self):
        self.table = _FakeTable()
        self.service = OAuthAuthorizationSessionService()
        self.service.table = self.table

    @patch.dict(
        "os.environ",
        {
            "INTEGRATION_SECRETS_MASTER_KEY_V1": base64.b64encode(b"12345678901234567890123456789012").decode("ascii")
        },
        clear=False,
    )
    def test_create_and_resolve_session_with_code_verifier(self):
        state, session = self.service.create_session(
            module_id="mercadolivre",
            app_profile_id="profile-1",
            installed_integration_id="inst-1",
            redirect_uri="https://app.example.com/callback",
            code_verifier="verifier-123",
        )

        resolved = self.service.get_session_by_state("mercadolivre", state)

        self.assertEqual(resolved["id"], session["id"])
        self.assertNotEqual(resolved["state_hash"], state)
        self.assertEqual(self.service.decode_code_verifier(resolved), "verifier-123")

    def test_invalid_state_is_rejected(self):
        with self.assertRaises(OAuthSessionError):
            self.service.get_session_by_state("mercadolivre", "missing-state")

    def test_expired_state_is_rejected(self):
        state, session = self.service.create_session(
            module_id="mercadolivre",
            app_profile_id="profile-1",
            installed_integration_id="inst-1",
            redirect_uri="https://app.example.com/callback",
        )
        session["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()

        with self.assertRaises(OAuthSessionError):
            self.service.get_session_by_state("mercadolivre", state)

    def test_consumed_state_is_single_use(self):
        state, session = self.service.create_session(
            module_id="mercadolivre",
            app_profile_id="profile-1",
            installed_integration_id="inst-1",
            redirect_uri="https://app.example.com/callback",
        )

        self.service.mark_consumed(session["id"])

        with self.assertRaises(OAuthSessionError):
            self.service.get_session_by_state("mercadolivre", state)


if __name__ == "__main__":
    unittest.main()
