from __future__ import annotations

from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.integration_provider_registry import (
    get_provider_spec,
)
from nistiprint_shared.services.integration_secret_service import (
    integration_secret_service,
)


class IntegrationAppProfileService:
    def __init__(self) -> None:
        self.table = supabase_db.table("integration_app_profiles")

    def list_profiles(self, module_id: str | None = None) -> list[dict]:
        query = self.table.select("*").order("name")
        if module_id:
            query = query.eq("module_id", module_id)
        response = query.execute()
        return response.data or []

    def get_profile(self, profile_id: Any) -> dict | None:
        response = self.table.select("*").eq("id", profile_id).limit(1).execute()
        if not response.data:
            return None
        return response.data[0]

    def get_default_profile(self, module_id: str) -> dict | None:
        response = (
            self.table.select("*")
            .eq("module_id", module_id)
            .eq("is_active", True)
            .eq("is_default", True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]

        fallback = (
            self.table.select("*")
            .eq("module_id", module_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        return fallback.data[0] if fallback.data else None

    def _normalize_secret_payload(
        self, module_id: str, secrets: dict[str, str] | None, *, require_required: bool
    ) -> dict[str, str]:
        spec = get_provider_spec(module_id)
        normalized: dict[str, str] = {}
        if not spec:
            return normalized

        payload = dict(secrets or {})
        allowed_keys = set(spec.app_profile_secret_kinds)

        for field in spec.app_profile_secret_fields:
            candidate_keys = (field.secret_kind, *field.aliases)
            for key in candidate_keys:
                value = payload.get(key)
                if value not in (None, ""):
                    normalized[field.secret_kind] = str(value).strip()
                    break

        unknown_keys = [
            key for key, value in payload.items() if value not in (None, "") and key not in allowed_keys and key not in {
                alias for field in spec.app_profile_secret_fields for alias in field.aliases
            }
        ]
        if unknown_keys:
            raise ValueError(
                f"Campos de segredo nao suportados para {module_id}: {', '.join(sorted(unknown_keys))}"
            )

        missing = []
        if require_required:
            missing = [
                field.label
                for field in spec.app_profile_secret_fields
                if field.required and normalized.get(field.secret_kind) in (None, "")
            ]
        if missing:
            raise ValueError(
                f"Campos obrigatorios ausentes para {module_id}: {', '.join(missing)}"
            )
        return normalized

    def create_profile(self, payload: dict, secrets: dict[str, str] | None = None) -> dict:
        module_id = str(payload.get("module_id") or "")
        if not get_provider_spec(module_id):
            raise ValueError(f"Modulo sem spec de credenciais: {module_id}")

        response = self.table.insert(payload).execute()
        profile = response.data[0]
        for secret_kind, value in self._normalize_secret_payload(
            module_id, secrets, require_required=True
        ).items():
            if value not in (None, ""):
                integration_secret_service.put_secret(
                    "app_profile", profile["id"], secret_kind, value
                )
        return profile

    def update_profile(
        self, profile_id: Any, payload: dict, secrets: dict[str, str] | None = None
    ) -> dict | None:
        current = self.get_profile(profile_id)
        if not current:
            return None
        module_id = str(payload.get("module_id") or current.get("module_id") or "")
        response = self.table.update(payload).eq("id", profile_id).execute()
        if not response.data:
            return None
        for secret_kind, value in self._normalize_secret_payload(
            module_id, secrets, require_required=False
        ).items():
            if value in (None, ""):
                continue
            integration_secret_service.put_secret(
                "app_profile", profile_id, secret_kind, value
            )
        return response.data[0]

    def get_profile_with_secrets(self, profile_id: Any) -> dict | None:
        profile = self.get_profile(profile_id)
        if not profile:
            return None
        return {
            **profile,
            "secrets": integration_secret_service.get_secret_map(
                "app_profile", profile_id
            ),
        }


integration_app_profile_service = IntegrationAppProfileService()
