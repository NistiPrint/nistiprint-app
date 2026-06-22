from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from firebase_admin import firestore

from nistiprint_shared.services.credential_resolver_service import (
    credential_resolver_service,
)
from nistiprint_shared.services.firebase.firebase import initialize_firebase


logger = logging.getLogger("BlingFirebaseProjection")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class BlingFirebaseProjectionService:
    collection_name = "bling_accounts"

    def _get_collection(self):
        if not initialize_firebase():
            raise RuntimeError("Firebase indisponivel para projeção de credenciais Bling.")
        return firestore.client().collection(self.collection_name)

    def _doc_id_for(self, installation: dict) -> str:
        config = installation.get("config") or {}
        cnpj = str(config.get("cnpj") or "").strip()
        firebase_doc_id = str(config.get("firebase_doc_id") or "").strip()
        if firebase_doc_id:
            return firebase_doc_id
        if cnpj:
            return cnpj
        return f"installed_integration_{installation.get('id')}"

    def build_payload(self, installation: dict) -> dict:
        context = credential_resolver_service.resolve_for_installation(installation)
        config = context.config or {}
        credentials = context.credentials or {}
        installation_secrets = context.installation_secrets or {}
        now = _now_utc()

        expires_at = _parse_dt(installation.get("expires_at"))
        expires_in = credentials.get("expires_in")
        if expires_in in (None, "") and expires_at:
            expires_in = max(0, int((expires_at - now).total_seconds()))

        payload = {
            "cnpj": config.get("cnpj"),
            "account_name": installation.get("instance_name"),
            "company_id": config.get("company_id") or credentials.get("company_id"),
            "access_token": installation_secrets.get("access_token"),
            "refresh_token": installation_secrets.get("refresh_token"),
            "updated_at": now,
            "last_token_update_utc": now,
            "token_expires_in": int(expires_in or 0),
            "instance_name": installation.get("instance_name"),
            "integration_id": installation.get("id"),
            "source_system": "supabase",
        }

        refresh_error = installation.get("refresh_error")
        if refresh_error:
            payload["last_token_update_error"] = str(refresh_error)
        else:
            payload["last_token_update_error"] = None

        return payload

    def publish_installation(self, installation: dict) -> dict:
        if str(installation.get("module_id") or "").lower() != "bling":
            raise ValueError("A projeção para Firebase suporta apenas instalações Bling.")

        doc_id = self._doc_id_for(installation)
        payload = self.build_payload(installation)
        self._get_collection().document(doc_id).set(payload, merge=True)

        logger.info(
            "Credenciais Bling publicadas no Firebase. integration_id=%s doc_id=%s",
            installation.get("id"),
            doc_id,
        )
        return {"doc_id": doc_id, "payload": payload}

    def publish_installation_by_id(self, installation_id: Any) -> dict:
        from nistiprint_shared.services.installed_integration_service import (
            installed_integration_service,
        )

        inst = installed_integration_service.get_installed_by_id(str(installation_id))
        if not inst:
            raise ValueError(f"Integração Bling {installation_id} não encontrada.")
        return self.publish_installation({**inst.to_dict(), "id": inst.id})

    def publish_all_active_bling(self) -> dict:
        from nistiprint_shared.services.installed_integration_service import (
            installed_integration_service,
        )

        integrations = installed_integration_service.get_installed_by_module("bling")
        published = 0
        failed = 0
        errors: list[dict[str, str]] = []

        for inst in integrations:
            try:
                self.publish_installation({**inst.to_dict(), "id": inst.id})
                published += 1
            except Exception as exc:  # pragma: no cover - defensive runtime path
                failed += 1
                errors.append({"integration_id": str(inst.id), "error": str(exc)})
                logger.error(
                    "Falha ao publicar integração Bling %s no Firebase: %s",
                    inst.id,
                    exc,
                )

        return {
            "status": "success" if failed == 0 else "partial_success",
            "published": published,
            "failed": failed,
            "errors": errors,
        }


bling_firebase_projection_service = BlingFirebaseProjectionService()
