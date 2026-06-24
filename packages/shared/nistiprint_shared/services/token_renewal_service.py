from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.credential_resolver_service import (
    credential_resolver_service,
)
from nistiprint_shared.services.installed_integration_service import (
    installed_integration_service,
)
from nistiprint_shared.services.integration_credentials_service import (
    integration_credentials_service,
)
from nistiprint_shared.services.integration_provider_registry import (
    normalize_provider_module_id,
)

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


class TokenRenewalService:
    """Servico compartilhado para renovacao agendada de tokens."""

    def _load_active_integrations(self) -> list[dict]:
        response = (
            supabase_db.client.table("installed_integrations")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        return response.data or []

    def _record_failure(self, integration_id: str, instance_name: str, exc: Exception) -> None:
        logger.error("Erro ao renovar token para %s: %s", instance_name, exc)
        try:
            now_iso = _now_utc().isoformat()
            installed_integration_service.update_installed(
                integration_id,
                {
                    "last_refresh_attempt": now_iso,
                    "refresh_error": str(exc),
                },
            )
            installed_integration_service.log_table.insert(
                {
                    "integration_id": integration_id,
                    "status": "error",
                    "message": str(exc),
                    "execution_mode": "scheduled",
                    "created_at": now_iso,
                }
            ).execute()
        except Exception as log_error:
            logger.error(
                "Erro ao registrar falha de renovacao da integracao %s: %s",
                integration_id,
                log_error,
            )

    def _should_renew(
        self,
        integration: dict,
        *,
        now: datetime,
        expiry_threshold: timedelta,
        retry_cooldown: timedelta,
    ) -> tuple[bool, str]:
        strategy = integration_credentials_service.strategy_for(integration)
        if strategy.management_mode != "app_managed" or not strategy.supports_refresh:
            return False, "unsupported_strategy"

        has_access_token = credential_resolver_service.has_installation_token(
            integration, "access_token"
        )
        has_refresh_token = credential_resolver_service.has_installation_token(
            integration, "refresh_token"
        )

        if not has_refresh_token:
            return False, "missing_refresh_token"

        # Refresh tokens OAuth podem ser rotativos. Depois de uma falha, respeite o
        # cooldown antes de considerar expiracao/acesso ausente; caso contrario uma
        # credencial invalid_grant e tentada novamente em toda execucao do Beat.
        refresh_error = integration.get("refresh_error")
        if refresh_error:
            last_refresh_attempt = _parse_dt(integration.get("last_refresh_attempt"))
            if last_refresh_attempt and last_refresh_attempt > now - retry_cooldown:
                return False, "cooldown_active"
            return True, "refresh_error"

        if not has_access_token:
            return True, "missing_access_token"

        expires_at = _parse_dt(integration.get("expires_at"))
        if expires_at and expires_at <= now + expiry_threshold:
            return True, "expiring"

        return False, "not_expiring"

    def renew_app_managed_credentials(
        self,
        expiry_threshold: timedelta = timedelta(hours=3),
        retry_cooldown: timedelta = timedelta(hours=6),
        module_filter: str | None = None,
    ) -> dict:
        logger.info(
            "Iniciando renovacao agendada de credenciais app_managed. "
            "expiry_threshold=%s retry_cooldown=%s module_filter=%s",
            expiry_threshold,
            retry_cooldown,
            module_filter,
        )

        normalized_filter = (
            normalize_provider_module_id(module_filter) if module_filter else None
        )
        now = _now_utc()
        integrations = self._load_active_integrations()

        by_module: dict[str, dict[str, int]] = defaultdict(
            lambda: {"processed": 0, "renewed": 0, "failed": 0, "skipped": 0}
        )
        skip_reasons: dict[str, int] = defaultdict(int)

        processed = 0
        renewed = 0
        failed = 0
        skipped = 0

        for integration in integrations:
            module_id = normalize_provider_module_id(integration.get("module_id"))
            if normalized_filter and module_id != normalized_filter:
                continue

            processed += 1
            by_module[module_id]["processed"] += 1

            should_renew, decision_reason = self._should_renew(
                integration,
                now=now,
                expiry_threshold=expiry_threshold,
                retry_cooldown=retry_cooldown,
            )

            if not should_renew:
                skipped += 1
                by_module[module_id]["skipped"] += 1
                skip_reasons[decision_reason] += 1
                logger.info(
                    "Pulando renovacao da integracao %s (%s): %s",
                    integration.get("id"),
                    integration.get("instance_name", f"ID {integration.get('id')}"),
                    decision_reason,
                )
                continue

            integration_id = str(integration.get("id"))
            instance_name = integration.get("instance_name", f"ID {integration_id}")
            logger.info(
                "Renovando credencial app_managed para %s (%s): %s",
                instance_name,
                module_id,
                decision_reason,
            )

            try:
                installed_integration_service.renew_integration_token(
                    integration_id,
                    execution_mode="scheduled",
                )
                renewed += 1
                by_module[module_id]["renewed"] += 1
            except Exception as exc:
                failed += 1
                by_module[module_id]["failed"] += 1
                self._record_failure(integration_id, instance_name, exc)

        module_label = normalized_filter or "todos"
        status = "SUCCESS"
        if failed and renewed:
            status = "PARTIAL_SUCCESS"
        elif failed:
            status = "FAILED"

        result = {
            "status": status,
            "message": (
                "Renovacao de credenciais app_managed concluida"
                if not normalized_filter
                else f"Renovacao de credenciais {module_label} concluida"
            ),
            "processed": processed,
            "renewed": renewed,
            "failed": failed,
            "skipped": skipped,
            "by_module": dict(by_module),
            "skip_reasons": dict(skip_reasons),
        }
        logger.info("Resultado da renovacao agendada: %s", result)
        return result

    def renew_shopee_tokens_expiring_soon(
        self, expiry_threshold: timedelta = timedelta(hours=3)
    ) -> dict:
        logger.info(
            "Delegando renovacao agendada de tokens Shopee para o fluxo unificado."
        )
        return self.renew_app_managed_credentials(
            expiry_threshold=expiry_threshold,
            module_filter="shopee",
        )

    def renew_mercadolivre_tokens_expiring_soon(
        self, expiry_threshold: timedelta = timedelta(hours=3)
    ) -> dict:
        logger.info(
            "Delegando renovacao agendada de tokens Mercado Livre para o fluxo unificado."
        )
        return self.renew_app_managed_credentials(
            expiry_threshold=expiry_threshold,
            module_filter="mercadolivre",
        )


token_renewal_service = TokenRenewalService()
