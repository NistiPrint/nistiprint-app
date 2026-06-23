from __future__ import annotations

from typing import Any

from nistiprint_shared.services.bling.bling_client import BlingClient


class BlingClientResolverService:
    def resolve_client(
        self,
        *,
        bling_integration_id: Any = None,
        marketplace_integration_id: Any = None,
        platform_name: str | None = None,
        channel_id: int | None = None,
        function_name: str = 'ORDER_IMPORT',
    ) -> tuple[BlingClient, int | None]:
        account_id = self._normalize_int(bling_integration_id)
        if account_id:
            return BlingClient.create_client_for_integration_id(account_id), account_id

        if marketplace_integration_id:
            from nistiprint_shared.services.integration_capability_service import (
                INVOICING,
                integration_capability_service,
            )

            resolved = integration_capability_service.resolve(str(marketplace_integration_id), INVOICING)
            account_id = self._normalize_int(resolved.integration_id)
            if account_id:
                return BlingClient.create_client_for_integration_id(account_id), account_id

        if not platform_name:
            raise ValueError('platform_name e obrigatorio quando nao ha bling_integration_id resolvido.')

        return BlingClient.create_client_for_platform(
            platform_name,
            channel_id=channel_id,
            function_name=function_name,
        ), account_id

    @staticmethod
    def _normalize_int(value: Any) -> int | None:
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


bling_client_resolver_service = BlingClientResolverService()
