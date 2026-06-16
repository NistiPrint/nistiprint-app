from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.integration_secret_service import (
    integration_secret_service,
)


class OAuthSessionError(RuntimeError):
    pass


class OAuthAuthorizationSessionService:
    def __init__(self) -> None:
        self.table = supabase_db.table("oauth_authorization_sessions")

    def _hash_state(self, state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    def create_session(
        self,
        *,
        module_id: str,
        app_profile_id: Any,
        installed_integration_id: Any,
        redirect_uri: str,
        return_to: str | None = None,
        code_verifier: str | None = None,
        ttl_minutes: int = 10,
    ) -> tuple[str, dict]:
        state = secrets.token_urlsafe(32)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        ).isoformat()
        payload = {
            "state_hash": self._hash_state(state),
            "module_id": module_id,
            "app_profile_id": app_profile_id,
            "installed_integration_id": installed_integration_id,
            "redirect_uri": redirect_uri,
            "return_to": return_to,
            "expires_at": expires_at,
            "status": "pending",
            "code_verifier_encrypted": integration_secret_service.encode_inline_secret(
                code_verifier
            )
            if code_verifier
            else None,
        }
        response = self.table.insert(payload).execute()
        return state, response.data[0]

    def get_session_by_state(
        self, module_id: str, state: str, *, allow_consumed: bool = False
    ) -> dict:
        response = (
            self.table.select("*")
            .eq("module_id", module_id)
            .eq("state_hash", self._hash_state(state))
            .limit(1)
            .execute()
        )
        if not response.data:
            raise OAuthSessionError("Sessao OAuth invalida.")

        session_row = response.data[0]
        expires_at = session_row.get("expires_at")
        if expires_at and datetime.fromisoformat(
            expires_at.replace("Z", "+00:00")
        ) <= datetime.now(timezone.utc):
            raise OAuthSessionError("Sessao OAuth expirada.")
        if session_row.get("consumed_at") and not allow_consumed:
            raise OAuthSessionError("Sessao OAuth ja consumida.")
        if session_row.get("status") == "cancelled":
            raise OAuthSessionError("Sessao OAuth cancelada.")
        return session_row

    def decode_code_verifier(self, session_row: dict) -> str | None:
        encoded = session_row.get("code_verifier_encrypted")
        return integration_secret_service.decode_inline_secret(encoded) if encoded else None

    def mark_consumed(self, session_id: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        (
            self.table.update(
                {
                    "status": "consumed",
                    "consumed_at": now,
                    "updated_at": now,
                }
            )
            .eq("id", session_id)
            .execute()
        )

    def mark_error(self, session_id: Any, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        (
            self.table.update(
                {
                    "status": "error",
                    "error": error[:500],
                    "updated_at": now,
                }
            )
            .eq("id", session_id)
            .execute()
        )


oauth_authorization_session_service = OAuthAuthorizationSessionService()
