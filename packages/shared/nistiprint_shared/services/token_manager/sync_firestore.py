from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from firebase_admin import firestore

from nistiprint_shared.services.firebase.firebase import initialize_firebase
from nistiprint_shared.services.installed_integration_service import (
    installed_integration_service,
)
from nistiprint_shared.services.integration_app_profile_service import (
    integration_app_profile_service,
)
from nistiprint_shared.services.integration_secret_service import (
    integration_secret_service,
)
from nistiprint_shared.services.token_manager.firebase_projection import (
    bling_firebase_projection_service,
)


logger = logging.getLogger("SyncFirestore")


def _find_bling_installation_by_cnpj(cnpj: str):
    installations = installed_integration_service.get_installed_by_module("bling")
    normalized = str(cnpj or "").strip()
    for inst in installations:
        config = inst.config or {}
        if str(config.get("cnpj") or "").strip() == normalized:
            return inst
    return None


def _coerce_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _resolve_bling_app_profile_id(inst, firebase_data: dict) -> int | None:
    if getattr(inst, "app_profile_id", None):
        return inst.app_profile_id

    profiles = integration_app_profile_service.list_profiles(module_id="bling")
    instance_name = str(getattr(inst, "instance_name", "") or "").lower()
    cnpj = str((inst.config or {}).get("cnpj") or firebase_data.get("cnpj") or "").strip()

    for profile in profiles:
        profile_name = str(profile.get("name") or "").lower()
        if cnpj and cnpj in profile_name:
            return profile.get("id")
        if instance_name and instance_name in profile_name:
            return profile.get("id")

    default_profile = integration_app_profile_service.get_default_profile("bling")
    return default_profile.get("id") if default_profile else None


def import_bling_credentials_from_firebase() -> dict:
    """
    Importa as credenciais atuais do Firebase para o cofre interno do app.

    Este fluxo existe para bootstrap/cutover. O caminho operacional padrão
    depois do corte é o oposto: app -> Firebase.
    """
    logger.info("[SYNC] Iniciando bootstrap Firebase -> app para contas Bling.")

    if not initialize_firebase():
        raise RuntimeError("Falha ao inicializar Firebase para importação de credenciais.")

    db = firestore.client()
    docs = db.collection("bling_accounts").stream()

    processed = 0
    migrated = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    for doc in docs:
        processed += 1
        data = doc.to_dict() or {}
        cnpj = str(data.get("cnpj") or "").strip()
        if not cnpj:
            skipped += 1
            errors.append({"doc_id": doc.id, "error": "cnpj ausente"})
            continue

        inst = _find_bling_installation_by_cnpj(cnpj)
        if not inst:
            skipped += 1
            errors.append(
                {
                    "doc_id": doc.id,
                    "cnpj": cnpj,
                    "error": "instalacao Bling nao encontrada por cnpj",
                }
            )
            continue

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if access_token not in (None, ""):
            integration_secret_service.put_secret(
                "installed_integration",
                inst.id,
                "access_token",
                access_token,
            )
        if refresh_token not in (None, ""):
            integration_secret_service.rotate_secret(
                "installed_integration",
                inst.id,
                "refresh_token",
                refresh_token,
            )

        updated_at = _coerce_dt(data.get("updated_at")) or _coerce_dt(
            data.get("last_token_update_utc")
        )
        expires_in = int(data.get("token_expires_in") or data.get("expires_in") or 0)
        expires_at = (
            (updated_at + timedelta(seconds=expires_in)).isoformat()
            if updated_at and expires_in > 0
            else None
        )

        current_config = dict(inst.config or {})
        current_config.setdefault("cnpj", cnpj)
        current_config["firebase_doc_id"] = doc.id
        if data.get("company_id") not in (None, ""):
            current_config["company_id"] = data.get("company_id")

        current_credentials = dict(inst.credentials or {})
        if expires_in > 0:
            current_credentials["expires_in"] = expires_in

        installed_integration_service.update_installed(
            str(inst.id),
            {
                "app_profile_id": _resolve_bling_app_profile_id(inst, data),
                "config": current_config,
                "credentials": current_credentials,
                "expires_at": expires_at,
                "refresh_error": None,
                "sync_status": "active",
            },
        )
        migrated += 1

    result = {
        "status": "success" if not errors else "partial_success",
        "processed": processed,
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info("[SYNC] Bootstrap Firebase -> app finalizado: %s", result)
    return result


def publish_bling_credentials_to_firebase() -> dict:
    """
    Publica as credenciais Bling gerenciadas pelo app no Firebase.
    """
    logger.info("[SYNC] Publicando credenciais Bling do app para o Firebase.")
    result = bling_firebase_projection_service.publish_all_active_bling()
    logger.info("[SYNC] Publicação app -> Firebase finalizada: %s", result)
    return result


def sync_bling_to_supabase():
    """
    Compatibilidade legada: mantém o nome antigo para o bootstrap inicial.
    """
    return import_bling_credentials_from_firebase()


if __name__ == "__main__":
    import_bling_credentials_from_firebase()
