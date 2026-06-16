from __future__ import annotations

from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
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

    def create_profile(self, payload: dict, secrets: dict[str, str] | None = None) -> dict:
        response = self.table.insert(payload).execute()
        profile = response.data[0]
        for secret_kind, value in (secrets or {}).items():
            if value not in (None, ""):
                integration_secret_service.put_secret(
                    "app_profile", profile["id"], secret_kind, value
                )
        return profile

    def update_profile(
        self, profile_id: Any, payload: dict, secrets: dict[str, str] | None = None
    ) -> dict | None:
        response = self.table.update(payload).eq("id", profile_id).execute()
        if not response.data:
            return None
        for secret_kind, value in (secrets or {}).items():
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
