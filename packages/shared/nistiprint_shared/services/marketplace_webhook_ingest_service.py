import logging
import os
import traceback
from dataclasses import replace
from datetime import datetime
from time import perf_counter
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.credential_resolver_service import (
    credential_resolver_service,
)
from nistiprint_shared.services.marketplace_adapters import (
    mercadolivre_adapter,
    shopee_adapter,
)
from nistiprint_shared.services.marketplace_rollout_service import (
    marketplace_rollout_service,
)
from nistiprint_shared.services.canonical_order_snapshot_service import (
    canonical_order_snapshot_service,
)
from nistiprint_shared.services.canonical_order_repository import (
    canonical_order_repository,
)
from nistiprint_shared.services.correlation_service import generate_correlation_id, set_correlation_id
from nistiprint_shared.services.logistica_coleta_service import logistica_coleta_service
from nistiprint_shared.services import logistics_canonicalization
from nistiprint_shared.services.modalidade_logistica_service import classify_pedido as classify_modalidade_logistica
from nistiprint_shared.services.personalized_classification_service import (
    persist_classification_from_payload,
)
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver
from nistiprint_shared.services.marketplace_account_identity import (
    account_identity_kind,
    account_identity_matches,
    has_account_identity,
    integration_account_identifiers,
    normalize_account_identifier,
)
from nistiprint_shared.utils.date_utils import get_now_iso, unix_to_app_iso

logger = logging.getLogger(__name__)


def _first_present(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _response_data(response, default=None):
    return getattr(response, "data", default)


def _extract_resource_id(resource: str | None, marker: str) -> str | None:
    if not resource or marker not in resource:
        return None
    tail = resource.rstrip("/").split(marker, 1)[-1].strip("/")
    if not tail:
        return None
    return tail.split("/", 1)[0].strip() or None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _summarize_timestamps(data_compra=None, data_pagamento=None, data_envio=None, status=None):
    return {
        "data_compra": data_compra,
        "data_pagamento": data_pagamento,
        "data_envio": data_envio,
        "status": status,
    }


def _meli_date_approved(order: dict) -> str | None:
    payments = order.get("payments") or []
    if not isinstance(payments, list):
        return None
    for payment in payments:
        if isinstance(payment, dict) and payment.get("date_approved"):
            return payment.get("date_approved")
    return None


class MarketplaceWebhookIngestService:
    def process(
        self,
        source: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        webhook_event_id: int | None = None,
    ) -> dict:
        source = str(source or "").strip().lower()
        correlation_id = correlation_id or generate_correlation_id()
        set_correlation_id(correlation_id)
        started = perf_counter()

        if source not in ("shopee", "mercadolivre"):
            return {
                "status": "error",
                "error_type": "unsupported_source",
                "message": f"source nao suportado: {source}",
                "correlation_id": correlation_id,
            }

        payload = payload or {}
        try:
            if source == "shopee":
                result = self._process_shopee(payload, correlation_id=correlation_id, webhook_event_id=webhook_event_id)
            else:
                result = self._process_mercadolivre(payload, correlation_id=correlation_id, webhook_event_id=webhook_event_id)

            self._update_webhook_event_from_result(webhook_event_id, result)
            self._write_ingest_log(
                correlation_id=correlation_id,
                stage=f"{source}_webhook_done",
                status=result.get("status"),
                message=result.get("message"),
                duration_ms=int((perf_counter() - started) * 1000),
                payload_summary={
                    "source": source,
                    "external_order_id": result.get("external_order_id"),
                    "marketplace_integration_id": result.get("marketplace_integration_id"),
                    "status": result.get("status"),
                    "event_status": result.get("event_status"),
                },
                pedido_id=result.get("pedido_id"),
                marketplace_integration_id=result.get("marketplace_integration_id"),
            )
            return {**result, "correlation_id": correlation_id}
        except Exception as exc:
            message = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.error("[marketplace-ingest] erro source=%s: %s", source, exc, exc_info=True)
            self._write_ingest_log(
                correlation_id=correlation_id,
                stage=f"{source}_webhook_failed",
                status="failed",
                message=message,
                duration_ms=int((perf_counter() - started) * 1000),
                payload_summary={"source": source},
            )
            return {
                "status": "error",
                "error_type": "processing_error",
                "message": str(exc),
                "correlation_id": correlation_id,
            }

    def _process_shopee(self, payload: dict, *, correlation_id: str, webhook_event_id: int | None = None) -> dict:
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        resolution = shopee_adapter.parse_webhook(payload)
        resource = resolution.primary_resource
        if resolution.classification in {"verification", "unsupported"}:
            return {
                "status": "skipped",
                "event_status": "skipped_unsupported_event",
                "resolution_status": resolution.status,
                "message": resolution.message,
                "retryable": False,
            }
        if resolution.classification == "chat":
            return {
                "status": "skipped",
                "event_status": "skipped_misrouted_chat_event",
                "resolution_status": "misrouted_chat",
                "provider_resource_type": "chat",
                "provider_resource_id": resource.resource_id if resource else None,
                "message": "SellerChat deve ser processado exclusivamente pela fila de chat",
                "retryable": False,
            }
        if not resource:
            return {
                "status": "error",
                "event_status": resolution.status,
                "resolution_status": resolution.status,
                "error_type": resolution.error_type or "invalid_provider_resource",
                "message": resolution.message or "Webhook Shopee invalido",
                "retryable": False,
            }

        order_sn = resource.resource_id
        marketplace_inst, resolution_error = self._resolve_marketplace_integration(
            "shopee",
            account_identifier=resource.account_id,
            external_order_id=order_sn,
        )
        metadata = {
            "provider_topic": resource.topic,
            "provider_resource": resource.resource_path,
            "provider_resource_type": resource.resource_type,
            "provider_resource_id": resource.resource_id,
            "resolved_order_ids": [order_sn],
        }
        if resolution_error:
            return {**resolution_error, **metadata, "resolution_status": "integration_unresolved"}

        link = self._find_direct_ingest_link(marketplace_inst.get("id"))
        inactive = self._inactive_source_result(
            "shopee", link, order_sn, marketplace_inst, payload=payload
        )
        if inactive:
            return {**inactive, **metadata, "resolution_status": "resolved"}
        integration = credential_resolver_service.hydrate_integration(marketplace_inst)
        snapshot = shopee_adapter.fetch_order_snapshot(order_sn, integration)
        if (
            isinstance(snapshot, dict)
            and snapshot.get("error_type") == "credential_action_required"
        ):
            refreshed = self._renew_marketplace_integration_once(marketplace_inst)
            if refreshed:
                marketplace_inst = refreshed
                integration = credential_resolver_service.hydrate_integration(refreshed)
                snapshot = shopee_adapter.fetch_order_snapshot(order_sn, integration)
        if isinstance(snapshot, dict):
            logger.warning(
                "[marketplace-webhook] shopee detail unavailable order_sn=%s integration_id=%s error_type=%s",
                order_sn,
                marketplace_inst.get("id"),
                snapshot.get("error_type"),
            )
            return {
                "status": "error",
                "event_status": snapshot.get("error_type") or "shopee_detail_unavailable",
                "error_type": snapshot.get("error_type") or "shopee_detail_unavailable",
                "message": snapshot.get("error"),
                "retryable": bool(snapshot.get("retryable")),
                "retry_after": snapshot.get("retry_after"),
                "external_order_id": order_sn,
                "marketplace_integration_id": marketplace_inst.get("id"),
                "resolution_status": "provider_error",
                **metadata,
            }
        detail = snapshot.raw

        logger.info(
            "[marketplace-webhook] shopee detail fetched order_sn=%s status=%s",
            order_sn,
            detail.get("order_status"),
        )

        pedido_shopee_id = self._upsert_shopee_mirror(detail, marketplace_inst.get("id"))
        status_original = detail.get("order_status") or body.get("order_status")
        rollout = marketplace_rollout_service.normalize(
            "shopee", snapshot, body, marketplace_inst
        )
        lifecycle = rollout.lifecycle
        rollout_comparison = rollout.comparison()
        pedido_id = self._upsert_pedido_status(
            source="shopee", external_order_id=order_sn,
            marketplace_integration_id=marketplace_inst.get("id"),
            bling_integration_id=(link or {}).get("bling_integration_id") or (link or {}).get("erp_integration_id"), bling_loja_id=(link or {}).get("aggregator_store_id") or (link or {}).get("erp_store_id"),
            channel_id=(link or {}).get("channel_id"),
            ingest_origin_mode=(link or {}).get("ingest_origin_mode"),
            situacao_pedido_id=lifecycle.target_situacao_pedido_id,
            status_original=status_original,
            lifecycle_event={
                **lifecycle.to_event(),
                "webhook_event_id": webhook_event_id,
                "provider_event_id": resource.provider_event_id,
                "adapter_mode": rollout.mode,
                "shadow_comparison": rollout_comparison,
                "marketplace_integration_id": marketplace_inst.get("id"),
            },
            mirror_fields={"pedido_shopee_id": pedido_shopee_id},
            raw_customer=self._shopee_customer(detail), total=detail.get("total"),
            currency=detail.get("currency") or "BRL", data_venda=detail.get("create_time"),
            details=detail,
        )
        return {
            "status": "success", "message": f"Pedido Shopee {order_sn} atualizado pelo marketplace",
            "pedido_id": pedido_id, "pedido_ids": [pedido_id] if pedido_id else [],
            "external_order_id": order_sn,
            "marketplace_integration_id": marketplace_inst.get("id"),
            "internal_situacao_pedido_id": lifecycle.target_situacao_pedido_id,
            "external_status_id": lifecycle.order_status,
            "lifecycle_stage": lifecycle.lifecycle_stage,
            "provider_updated_at": lifecycle.observed_at,
            "resolution_status": "resolved",
            "adapter_mode": rollout.mode,
            "shadow_comparison": rollout_comparison if rollout.mode == "shadow" else None,
            **metadata,
        }

    def _process_mercadolivre(self, payload: dict, *, correlation_id: str, webhook_event_id: int | None = None) -> dict:
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        parsed = mercadolivre_adapter.parse_webhook(payload)
        resource = parsed.primary_resource
        if parsed.classification == "unsupported":
            return {
                "status": "skipped",
                "event_status": "skipped_unsupported_topic",
                "resolution_status": parsed.status,
                "skip_reason": parsed.status,
                "message": parsed.message,
                "provider_topic": str(body.get("topic") or "").strip().lower() or None,
                "retryable": False,
            }
        if not resource:
            return {
                "status": "error",
                "event_status": parsed.status,
                "resolution_status": parsed.status,
                "error_type": parsed.error_type or "invalid_provider_resource",
                "message": parsed.message or "Webhook Mercado Livre invalido",
                "retryable": False,
            }
        metadata = {
            "provider_topic": resource.topic,
            "provider_resource": resource.resource_path,
            "provider_resource_type": resource.resource_type,
            "provider_resource_id": resource.resource_id,
        }

        marketplace_inst, resolution_error = self._resolve_marketplace_integration(
            "mercadolivre",
            account_identifier=resource.account_id,
            external_order_id=parsed.primary_order_id,
        )
        if resolution_error:
            return {**resolution_error, **metadata, "resolution_status": "integration_unresolved"}
        integration = self._meli_integration(marketplace_inst)
        resolved = mercadolivre_adapter.resolve_order_ids(
            resource,
            integration,
            payment_lookup=lambda payment_id: self._lookup_meli_order_by_payment_id(
                marketplace_inst.get("id"), payment_id
            ),
            shipment_lookup=lambda shipment_id: self._lookup_meli_order_by_shipment_id(
                marketplace_inst.get("id"), shipment_id
            ),
        )
        if resolved.error_type == "credential_action_required":
            refreshed = self._renew_marketplace_integration_once(marketplace_inst)
            if refreshed:
                marketplace_inst = refreshed
                integration = self._meli_integration(refreshed)
                resolved = mercadolivre_adapter.resolve_order_ids(
                    resource,
                    integration,
                    payment_lookup=lambda payment_id: self._lookup_meli_order_by_payment_id(
                        marketplace_inst.get("id"), payment_id
                    ),
                    shipment_lookup=lambda shipment_id: self._lookup_meli_order_by_shipment_id(
                        marketplace_inst.get("id"), shipment_id
                    ),
                )
        metadata["resolution_status"] = resolved.status
        metadata["resolved_order_ids"] = list(resolved.resolved_order_ids)
        if resolved.status == "unresolved_payment":
            return {
                "status": "skipped",
                "event_status": "skipped_unresolved_payment_reference",
                "skip_reason": "payment_without_order_reference",
                "message": "Pagamento Mercado Livre sem pedido associado; orders_v2 permanece autoritativo",
                "marketplace_integration_id": marketplace_inst.get("id"),
                "retryable": False,
                **metadata,
            }
        if resolved.error_type:
            return {
                "status": "error",
                "event_status": resolved.error_type,
                "error_type": resolved.error_type,
                "message": resolved.message,
                "retryable": resolved.retryable,
                "retry_after": resolved.retry_after,
                "marketplace_integration_id": marketplace_inst.get("id"),
                **metadata,
            }
        results = [
            self._process_meli_order(
                order_id,
                marketplace_inst=marketplace_inst,
                payload=payload,
                body=body,
                resource=resource,
                webhook_event_id=webhook_event_id,
                resolution_context=resolved.context,
            )
            for order_id in resolved.resolved_order_ids
        ]
        failure = next((row for row in results if row.get("status") not in {"success", "skipped"}), None)
        if failure:
            return {**failure, **metadata}
        successes = [row for row in results if row.get("status") == "success"]
        if not successes:
            first = results[0] if results else {
                "status": "error",
                "error_type": "missing_order_id",
                "message": "Recurso Mercado Livre nao resolveu pedidos",
                "retryable": False,
            }
            return {**first, **metadata}
        primary = successes[0]
        pedido_ids = [row.get("pedido_id") for row in successes if row.get("pedido_id")]
        return {
            **primary,
            "message": f"{len(successes)} pedido(s) Mercado Livre atualizado(s)",
            "pedido_ids": pedido_ids,
            "resolved_order_ids": list(resolved.resolved_order_ids),
            **metadata,
        }

    def _process_meli_order(
        self,
        order_id: str,
        *,
        marketplace_inst: dict,
        payload: dict,
        body: dict,
        resource,
        webhook_event_id: int | None,
        resolution_context: dict | None = None,
    ) -> dict:
        link = self._find_direct_ingest_link(marketplace_inst.get("id"))
        inactive = self._inactive_source_result(
            "mercadolivre", link, order_id, marketplace_inst, payload=payload
        )
        if inactive:
            return inactive
        snapshot = mercadolivre_adapter.fetch_order_snapshot(
            order_id, self._meli_integration(marketplace_inst)
        )
        if (
            isinstance(snapshot, dict)
            and snapshot.get("error_type") == "credential_action_required"
        ):
            refreshed = self._renew_marketplace_integration_once(marketplace_inst)
            if refreshed:
                marketplace_inst = refreshed
                snapshot = mercadolivre_adapter.fetch_order_snapshot(
                    order_id, self._meli_integration(refreshed)
                )
        if isinstance(snapshot, dict):
            logger.warning(
                "[marketplace-webhook] meli detail unavailable order_id=%s integration_id=%s error_type=%s",
                order_id,
                marketplace_inst.get("id"),
                snapshot.get("error_type"),
            )
            return {
                "status": "error",
                "event_status": snapshot.get("error_type") or "mercadolivre_detail_unavailable",
                "error_type": snapshot.get("error_type") or "mercadolivre_detail_unavailable",
                "message": snapshot.get("error"),
                "retryable": bool(snapshot.get("retryable")),
                "retry_after": snapshot.get("retry_after"),
                "external_order_id": order_id,
                "marketplace_integration_id": marketplace_inst.get("id"),
            }
        detail = dict(snapshot.raw)
        resolution_context = resolution_context or {}
        for key in ("claim", "return"):
            if isinstance(resolution_context.get(key), dict):
                detail[key] = resolution_context[key]
        if detail is not snapshot.raw:
            snapshot = replace(
                snapshot,
                raw=detail,
                return_status=(detail.get("return") or {}).get("status"),
            )
        logger.info(
            "[marketplace-webhook] meli detail fetched order_id=%s order_status=%s shipment_status=%s",
            order_id,
            snapshot.order_status,
            snapshot.shipping_status,
        )
        pedido_meli_id = self._upsert_meli_mirror(detail, marketplace_inst.get("id"))
        order = detail.get("order") or {}
        rollout = marketplace_rollout_service.normalize(
            "mercadolivre", snapshot, body, marketplace_inst
        )
        lifecycle = rollout.lifecycle
        rollout_comparison = rollout.comparison()
        payment_status = lifecycle.payment_status
        shipping_status = lifecycle.shipping_status
        status_original = (
            f"order:{lifecycle.order_status or '-'}|"
            f"payment:{payment_status or '-'}|"
            f"shipping:{shipping_status or '-'}|"
            f"substatus:{lifecycle.shipping_substatus or '-'}"
        )
        pedido_id = self._upsert_pedido_status(
            source="mercadolivre", external_order_id=order_id,
            marketplace_integration_id=marketplace_inst.get("id"),
            bling_integration_id=(link or {}).get("bling_integration_id") or (link or {}).get("erp_integration_id"), bling_loja_id=(link or {}).get("aggregator_store_id") or (link or {}).get("erp_store_id"),
            channel_id=(link or {}).get("channel_id"),
            ingest_origin_mode=(link or {}).get("ingest_origin_mode"),
            situacao_pedido_id=lifecycle.target_situacao_pedido_id,
            status_original=status_original,
            lifecycle_event={
                **lifecycle.to_event(),
                "webhook_event_id": webhook_event_id,
                "provider_event_id": resource.provider_event_id,
                "adapter_mode": rollout.mode,
                "shadow_comparison": rollout_comparison,
                "marketplace_integration_id": marketplace_inst.get("id"),
            },
            mirror_fields={"pedido_mercadolivre_id": pedido_meli_id},
            raw_customer=self._meli_customer(order), total=order.get("total_amount"),
            currency=order.get("currency_id") or "BRL", data_venda=order.get("date_created"),
            details=detail,
        )
        return {
            "status": "success", "message": f"Pedido Mercado Livre {order_id} atualizado pelo marketplace",
            "pedido_id": pedido_id, "external_order_id": order_id,
            "marketplace_integration_id": marketplace_inst.get("id"),
            "internal_situacao_pedido_id": lifecycle.target_situacao_pedido_id,
            "external_status_id": lifecycle.order_status,
            "status_domain": "lifecycle",
            "lifecycle_stage": lifecycle.lifecycle_stage,
            "provider_updated_at": lifecycle.observed_at,
            "provider_topic": resource.topic,
            "provider_resource": resource.resource_path,
            "provider_resource_type": resource.resource_type,
            "provider_resource_id": resource.resource_id,
            "resolution_status": "resolved",
            "adapter_mode": rollout.mode,
            "shadow_comparison": rollout_comparison if rollout.mode == "shadow" else None,
        }

    def _inactive_source_result(
        self, source: str, link: dict | None, external_order_id: str,
        marketplace_inst: dict, *, payload: dict | None = None,
    ) -> dict | None:
        if not link:
            return {
                "status": "skipped",
                "event_status": "skipped_inactive_source",
                "skip_reason": "missing_channel_connection",
                "message": f"Sem channel_connection ativa para {source} integration_id={marketplace_inst.get('id')}",
                "external_order_id": external_order_id,
                "marketplace_integration_id": marketplace_inst.get("id"),
            }

        ingest_origin_mode = link.get("ingest_origin_mode") or "erp_bling"
        if link.get("process_webhooks") is False:
            return {
                "status": "skipped",
                "event_status": "skipped_inactive_source",
                "skip_reason": "webhooks_disabled",
                "message": f"Webhook {source} desabilitado para a integracao",
                "external_order_id": external_order_id,
                "marketplace_integration_id": marketplace_inst.get("id"),
            }
        if ingest_origin_mode != "marketplace_direct":
            return self._erp_only_order_readiness(
                source=source,
                external_order_id=external_order_id,
                marketplace_inst=marketplace_inst,
                payload=payload,
            )
        return None

    def _erp_only_order_readiness(
        self,
        *,
        source: str,
        external_order_id: str,
        marketplace_inst: dict,
        payload: dict | None = None,
    ) -> dict | None:
        raw_payload = payload or {}
        links = self._find_bling_links(marketplace_inst)

        if links:
            lookup_error = None
            for link in links:
                bling_ref = self._lookup_bling_order(
                    bling_integration_id=link.get("erp_integration_id"),
                    external_order_id=str(external_order_id),
                )
                if bling_ref.get("status") == "found" and bling_ref.get("bling_order_number"):
                    logger.info(
                        "[marketplace-webhook] erp-only webhook liberado source=%s external_order_id=%s bling_integration_id=%s bling_order_number=%s",
                        source,
                        external_order_id,
                        link.get("erp_integration_id"),
                        bling_ref.get("bling_order_number"),
                    )
                    return None
                if bling_ref.get("status") == "error":
                    lookup_error = bling_ref

            if lookup_error and lookup_error.get("reason") in ("bling_rate_limited", "bling_lookup_transient_error"):
                return {
                    "status": "error",
                    "event_status": lookup_error.get("reason"),
                    "error_type": lookup_error.get("reason"),
                    "message": lookup_error.get("error") or "Falha temporaria ao consultar pedido no Bling",
                    "retry_after": lookup_error.get("retry_after"),
                    "external_order_id": external_order_id,
                    "marketplace_integration_id": marketplace_inst.get("id"),
                }

        source_event_id = _first_present(
            raw_payload.get("event_id"), raw_payload.get("code"),
            raw_payload.get("timestamp"), raw_payload.get("update_time"),
        )
        canonical_order_repository.queue_marketplace_enrichment(
            marketplace_integration_id=marketplace_inst.get("id"),
            marketplace_module_id=source,
            marketplace_order_id=external_order_id,
            payload=raw_payload,
            event_type=_first_present(raw_payload.get("event"), raw_payload.get("topic")),
            source_event_id=str(source_event_id) if source_event_id is not None else None,
        )
        return {
            "status": "pending",
            "event_status": "pending_erp_order",
            "error_type": "pending_dependency",
            "retryable": True,
            "message": f"Webhook {source} aguardando pedido importado pelo ERP",
            "external_order_id": external_order_id,
            "marketplace_integration_id": marketplace_inst.get("id"),
        }

    def _find_bling_links(self, marketplace_inst: dict | None) -> list[dict]:
        if not marketplace_inst or not marketplace_inst.get("id"):
            return []

        config = marketplace_inst.get("config") or {}
        default_link_id = _first_present(config.get("default_nfe_link_id"), config.get("default_nfe_erp_link_id"))
        default_erp_id = _first_present(
            config.get("default_nfe_erp_integration_id"),
            config.get("default_nfe_bling_integration_id"),
        )
        default_shop_id = _first_present(config.get("default_nfe_shop_id"), config.get("default_nfe_erp_store_id"))

        links = (
            supabase_db.table("erp_marketplace_links")
            .select("*")
            .eq("marketplace_integration_id", marketplace_inst.get("id"))
            .execute()
            .data
            or []
        )
        links = [
            dict(link)
            for link in links
            if (link.get("nf_emission_mode") or (link.get("config") or {}).get("nf_emission_mode") or "bling") == "bling"
        ]
        if not links:
            return []

        def priority(link: dict) -> tuple[int, int, str]:
            is_default_link = int(str(link.get("id")) == str(default_link_id)) if default_link_id else 0
            is_default_erp = int(
                bool(default_erp_id)
                and str(link.get("erp_integration_id")) == str(default_erp_id)
                and (not default_shop_id or str(link.get("erp_store_id")) == str(default_shop_id))
            )
            return (-is_default_link, -is_default_erp, str(link.get("id") or ""))

        return sorted(links, key=priority)

    def _find_default_nfe_link(self, marketplace_inst: dict | None) -> dict | None:
        links = self._find_bling_links(marketplace_inst)
        if len(links) == 1:
            return links[0]
        if links:
            first = links[0]
            config = (marketplace_inst or {}).get("config") or {}
            if config.get("default_nfe_link_id") or config.get("default_nfe_erp_link_id") or config.get("default_nfe_erp_integration_id") or config.get("default_nfe_bling_integration_id"):
                return first

        logger.warning(
            "[marketplace-webhook] default NF route missing/ambiguous integration_id=%s candidates=%s",
            (marketplace_inst or {}).get("id"),
            [link.get("id") for link in links],
        )
        return None

    def _active_marketplace_integrations(self, module_id: str) -> list[dict]:
        rows = (
            supabase_db.table("installed_integrations")
            .select("*")
            .eq("module_id", module_id)
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        return rows

    def _find_marketplace_integration(self, module_id: str, *, shop_id: Any = None) -> dict | None:
        integration, _error = self._resolve_marketplace_integration(
            module_id,
            account_identifier=shop_id,
        )
        return integration

    def _resolve_marketplace_integration(
        self,
        module_id: str,
        *,
        account_identifier: Any = None,
        external_order_id: str | None = None,
    ) -> tuple[dict | None, dict | None]:
        rows = self._active_marketplace_integrations(module_id)
        if not rows:
            return None, self._marketplace_resolution_error(
                module_id,
                "marketplace_integration_not_found",
                account_identifier,
                external_order_id,
                "Nenhuma integracao ativa encontrada para o marketplace",
            )

        normalized_identifier = normalize_account_identifier(account_identifier)
        if normalized_identifier:
            matches = [row for row in rows if account_identity_matches(row, normalized_identifier)]
            if len(matches) == 1:
                return matches[0], None
            if len(matches) > 1:
                return None, self._marketplace_resolution_error(
                    module_id,
                    "marketplace_integration_ambiguous",
                    normalized_identifier,
                    external_order_id,
                    "Mais de uma integracao corresponde ao identificador do marketplace",
                    candidates=matches,
                )
            return None, self._marketplace_resolution_error(
                module_id,
                "marketplace_integration_not_found",
                normalized_identifier,
                external_order_id,
                "Nenhuma integracao corresponde ao identificador do marketplace",
            )

        non_dummy = [row for row in rows if not (row.get("config") or {}).get("dummy")]
        candidates = non_dummy or rows
        if len(candidates) > 1:
            return None, self._marketplace_resolution_error(
                module_id,
                "marketplace_integration_ambiguous",
                normalized_identifier,
                external_order_id,
                "Webhook sem identificador confiavel e multiplas instancias ativas",
                candidates=candidates,
            )

        only_candidate = candidates[0]
        allow_legacy_single_fallback = os.getenv("MARKETPLACE_WEBHOOK_ALLOW_SINGLE_UNIDENTIFIED_FALLBACK", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if has_account_identity(only_candidate) or allow_legacy_single_fallback:
            return only_candidate, None

        return None, self._marketplace_resolution_error(
            module_id,
            "marketplace_integration_ambiguous",
            normalized_identifier,
            external_order_id,
            "Instancia unica sem identidade de webhook configurada",
            candidates=candidates,
        )

    def _marketplace_resolution_error(
        self,
        module_id: str,
        error_type: str,
        account_identifier: Any,
        external_order_id: str | None,
        message: str,
        *,
        candidates: list[dict] | None = None,
    ) -> dict:
        return {
            "status": "error",
            "event_status": error_type,
            "error_type": error_type,
            "message": message,
            "module_id": module_id,
            "expected_account_identifier_kind": account_identity_kind(module_id),
            "account_identifier": normalize_account_identifier(account_identifier),
            "external_order_id": external_order_id,
            "candidate_integration_ids": [row.get("id") for row in candidates or [] if row.get("id") is not None],
            "candidate_account_identifiers": {
                str(row.get("id")): sorted(integration_account_identifiers(row))
                for row in candidates or []
                if row.get("id") is not None
            },
            "retryable": error_type == "marketplace_integration_not_found",
        }

    def _find_direct_ingest_link(self, marketplace_integration_id: int | None) -> dict | None:
        if not marketplace_integration_id:
            return None

        # A consulta LE o modo, nao filtra por ele. Filtrar por
        # `marketplace_direct` aqui — como se fazia — tornava invisivel um
        # vinculo em `erp_bling` registrado so nesta tabela: a busca caia no
        # `channel_connections` e, sem linha la, o webhook virava
        # `skipped_inactive_source` em vez do `pending_erp_order` pretendido.
        link_rows = (
            supabase_db.table("erp_marketplace_links")
            .select(
                "id,erp_integration_id,marketplace_integration_id,process_webhooks,"
                "ingest_origin_mode,erp_store_id,channel_id"
            )
            .eq("marketplace_integration_id", marketplace_integration_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if link_rows:
            link = dict(link_rows[0])
            link["bling_integration_id"] = link.get("erp_integration_id")
            link["aggregator_store_id"] = link.get("erp_store_id")
            if link.get("channel_id") is None:
                # Vinculo ainda nao migrado: o canal vive no cadastro legado.
                link["channel_id"] = self._legacy_channel_id(marketplace_integration_id)
            return link

        rows = (
            supabase_db.table("channel_connections")
            .select("id,channel_id,bling_integration_id,marketplace_integration_id,process_webhooks,ingest_origin_mode,aggregator_store_id")
            .eq("marketplace_integration_id", marketplace_integration_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    def _legacy_channel_id(self, marketplace_integration_id: int | None) -> int | None:
        """Canal do cadastro legado, enquanto o backfill nao alcanca o vinculo."""
        if not marketplace_integration_id:
            return None
        try:
            rows = (
                supabase_db.table("channel_connections")
                .select("channel_id")
                .eq("marketplace_integration_id", marketplace_integration_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning(
                "[marketplace-webhook] falha ao resolver canal legado integration_id=%s: %s",
                marketplace_integration_id, exc,
            )
            return None
        return rows[0].get("channel_id") if rows else None

    def _hydrate_shopee_integration(self, marketplace_inst: dict) -> dict:
        credentials = marketplace_inst.get("credentials") or {}
        return credential_resolver_service.hydrate_integration({
            **dict(marketplace_inst),
            "config": marketplace_inst.get("config") or {},
            "credentials": credentials,
            "access_token": marketplace_inst.get("access_token") or credentials.get("access_token"),
        })

    def _fetch_shopee_detail(self, marketplace_inst: dict, order_sn: str) -> dict:
        return shopee_driver.get_order_detail(
            self._hydrate_shopee_integration(marketplace_inst), [order_sn]
        )

    def _lookup_meli_order_by_payment_id(
        self,
        marketplace_integration_id: int | None,
        payment_id: str,
    ) -> dict | None:
        if not marketplace_integration_id or not payment_id:
            return None
        numeric_payment_id = _as_int(payment_id)
        if numeric_payment_id is None:
            return None
        try:
            rows = (
                supabase_db.table("pedidos_mercadolivre")
                .select("codigo_pedido,raw_order")
                .eq("marketplace_integration_id", marketplace_integration_id)
                .contains("raw_order", {"payments": [{"id": numeric_payment_id}]})
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning(
                "[marketplace-webhook] failed payment mirror lookup integration_id=%s payment_id=%s error=%s",
                marketplace_integration_id,
                payment_id,
                exc,
            )
            return None
        if not rows:
            return None
        row = rows[0]
        payments = (row.get("raw_order") or {}).get("payments") or []
        payment = next(
            (
                item for item in payments
                if isinstance(item, dict) and str(item.get("id")) == str(payment_id)
            ),
            {},
        )
        return {
            "codigo_pedido": row.get("codigo_pedido"),
            "payment_status": payment.get("status"),
        }

    def _lookup_meli_order_by_shipment_id(
        self,
        marketplace_integration_id: int | None,
        shipment_id: str,
    ) -> dict | None:
        """Resolve shipment -> pedido pelo espelho local.

        O formato novo de /shipments/{id} nao devolve order_id nem pack_id,
        entao o espelho (que grava shipment_id na ingestao via orders_v2) evita
        uma chamada extra na API para descobrir o pedido do evento.
        """
        if not marketplace_integration_id or not shipment_id:
            return None
        numeric_shipment_id = _as_int(shipment_id)
        if numeric_shipment_id is None:
            return None
        try:
            rows = (
                supabase_db.table("pedidos_mercadolivre")
                .select("codigo_pedido")
                .eq("marketplace_integration_id", marketplace_integration_id)
                .eq("shipment_id", numeric_shipment_id)
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning(
                "[marketplace-webhook] failed shipment mirror lookup integration_id=%s shipment_id=%s error=%s",
                marketplace_integration_id,
                shipment_id,
                exc,
            )
            return None
        if not rows:
            return None
        return {"codigo_pedido": rows[0].get("codigo_pedido")}

    def _fetch_meli_detail(self, marketplace_inst: dict, order_id: str) -> dict:
        integration = self._meli_integration(marketplace_inst)
        order = meli_driver.get_order_detail(integration, [order_id])
        if not order or order.get("error"):
            return order or {"error": "Pedido nao encontrado no Mercado Livre"}

        shipment = {}
        sla = {}
        shipment_id = (order.get("shipping") or {}).get("id")
        if shipment_id:
            shipment = meli_driver.get_shipment(integration, str(shipment_id))
            sla = meli_driver.get_shipment_sla(integration, str(shipment_id))

        return {
            "external_id": order_id,
            "order": order,
            "shipment": shipment if isinstance(shipment, dict) else {},
            "sla": sla,
        }

    def _meli_integration(self, marketplace_inst: dict) -> dict:
        credentials = marketplace_inst.get("credentials") or {}
        return credential_resolver_service.hydrate_integration({
            **dict(marketplace_inst),
            "config": marketplace_inst.get("config") or {},
            "credentials": credentials,
            "access_token": marketplace_inst.get("access_token") or credentials.get("access_token"),
        })

    def _renew_marketplace_integration_once(
        self, marketplace_inst: dict
    ) -> dict | None:
        integration_id = marketplace_inst.get("id")
        if not integration_id:
            return None
        try:
            from nistiprint_shared.services.installed_integration_service import (
                installed_integration_service,
            )
            installed_integration_service.renew_integration_token(
                str(integration_id), execution_mode="webhook_401"
            )
            rows = (
                supabase_db.table("installed_integrations")
                .select("*")
                .eq("id", integration_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            return dict(rows[0]) if rows else None
        except Exception as exc:
            logger.warning(
                "[marketplace-webhook] credential renewal failed integration_id=%s error_type=%s",
                integration_id,
                type(exc).__name__,
            )
            return None

    def _upsert_shopee_mirror(self, detail: dict, marketplace_integration_id: int | None) -> int | None:
        if not marketplace_integration_id:
            return None
        from nistiprint_shared.services.bling_order_processing_service import _upsert_pedido_shopee

        return _upsert_pedido_shopee(detail, marketplace_integration_id)

    def _upsert_meli_mirror(self, detail: dict, marketplace_integration_id: int | None) -> int | None:
        if not marketplace_integration_id:
            return None
        from nistiprint_shared.services.bling_order_processing_service import _upsert_pedido_meli

        return _upsert_pedido_meli(detail, marketplace_integration_id)

    def _try_materialize_from_bling(
        self,
        *,
        source: str,
        external_order_id: str,
        marketplace_inst: dict,
        marketplace_detail: dict,
        marketplace_mirror_id: int | None,
        nfe_link: dict | None,
    ) -> dict | None:
        links = self._find_bling_links(marketplace_inst)
        if not links:
            return {
                "status": "error",
                "reason": "missing_bling_reference",
                "message": "Integracao Bling obrigatoria nao configurada para o marketplace",
            }

        if nfe_link and nfe_link.get("id"):
            prioritized = [
                dict(nfe_link),
                *[link for link in links if str(link.get("id")) != str(nfe_link.get("id"))],
            ]
        else:
            prioritized = links

        from nistiprint_shared.services.bling_order_processing_service import (
            materialize_marketplace_direct_order,
        )

        successes = []
        first_error = None
        for link in prioritized:
            result = materialize_marketplace_direct_order(
                source=source,
                external_order_id=str(external_order_id),
                marketplace_inst=marketplace_inst,
                marketplace_detail=marketplace_detail,
                marketplace_mirror_id=marketplace_mirror_id,
                bling_integration_id=link.get("erp_integration_id"),
                bling_loja_id=link.get("erp_store_id"),
            )
            if result.get("status") == "success":
                enriched = {
                    **result,
                    "selected_bling_integration_id": link.get("erp_integration_id"),
                    "selected_bling_store_id": link.get("erp_store_id"),
                }
                successes.append(enriched)
                continue
            if first_error is None or result.get("reason") != "bling_order_not_found":
                first_error = result

        if len(successes) == 1:
            return successes[0]
        if len(successes) > 1:
            return {
                "status": "error",
                "reason": "bling_order_ambiguous",
                "message": "Pedido encontrado em mais de uma conta Bling vinculada ao marketplace",
            }
        if first_error:
            logger.info(
                "[marketplace-webhook] bling materialization unavailable source=%s external_order_id=%s result=%s",
                source,
                external_order_id,
                {k: v for k, v in first_error.items() if k != "message"},
            )
            return first_error
        return {"status": "not_found", "reason": "bling_order_not_found"}

    def _bling_materialization_error_result(
        self,
        *,
        source: str,
        external_order_id: str,
        marketplace_integration_id: int | None,
        result: dict,
    ) -> dict:
        reason = result.get("reason") or "bling_order_unavailable"
        messages = {
            "missing_bling_reference": "Integracao Bling obrigatoria nao configurada para o marketplace",
            "bling_order_not_found": "Pedido ainda nao encontrado no Bling",
            "bling_lookup_failed": "Falha ao consultar o pedido no Bling",
            "bling_rate_limited": "Limite de requisicoes do Bling atingido",
            "bling_lookup_transient_error": "Bling temporariamente indisponivel",
            "bling_order_incomplete": "Pedido retornado pelo Bling sem id ou numero",
            "bling_detail_incomplete": "Detalhe do pedido Bling sem numero_pedido",
            "bling_materialization_failed": "Pedido Bling nao foi materializado",
            "bling_order_ambiguous": "Pedido encontrado em mais de uma conta Bling vinculada ao marketplace",
        }
        return {
            "status": "error",
            "event_status": reason,
            "error_type": reason,
            "message": result.get("message") or messages.get(reason) or "Pedido Bling indisponivel para materializacao",
            "external_order_id": external_order_id,
            "marketplace_integration_id": marketplace_integration_id,
            "retry_after": result.get("retry_after"),
        }

    @staticmethod
    def _sanitize_status_original(status_original: str | None) -> str | None:
        if status_original in (None, ""):
            return None
        value = str(status_original).strip()
        return value or None

    def _update_materialized_pedido_status(
        self,
        *,
        pedido_id: int | None,
        situacao_pedido_id: int | None,
        status_original: str | None,
        source: str,
    ) -> None:
        if not pedido_id:
            return

        status_original = self._sanitize_status_original(status_original)

        fields = {
            "status_original": status_original,
            "ingest_source": source,
            "updated_at": get_now_iso(),
        }
        if situacao_pedido_id is not None:
            fields["situacao_pedido_id"] = situacao_pedido_id
        fields = {key: value for key, value in fields.items() if value is not None}
        if not fields:
            return

        supabase_db.table("pedidos").update(fields).eq("id", pedido_id).execute()
        logger.info(
            "[marketplace-webhook] pedido materializado status sincronizado pedido_id=%s source=%s situacao=%s status_original=%s",
            pedido_id,
            source,
            situacao_pedido_id,
            status_original,
        )

    def _upsert_pedido_status(
        self,
        *,
        source: str,
        external_order_id: str,
        marketplace_integration_id: int | None,
        bling_integration_id: int | None,
        bling_loja_id: str | None,
        channel_id: int | None,
        ingest_origin_mode: str | None,
        situacao_pedido_id: int | None,
        status_original: str | None,
        mirror_fields: dict,
        lifecycle_event: dict | None = None,
        raw_customer: dict | None,
        total: Any,
        currency: str,
        data_venda: str | None,
        details: dict | None = None,
    ) -> int | None:
        if not external_order_id:
            return None

        # ERP is optional until printing or invoicing actually needs it.
        bling_ref = {}
        if bling_integration_id:
            try:
                local_rows = (supabase_db.table("pedidos_bling")
                    .select("id,bling_id,numero_pedido,numero_loja")
                    .eq("bling_integration_id", bling_integration_id)
                    .eq("numero_loja", str(external_order_id)).limit(1).execute().data or [])
                if local_rows:
                    local = local_rows[0]
                    bling_ref = {
                        "status": "found",
                        "pedido_bling_id": local.get("id"),
                        "bling_order_id": local.get("bling_id"),
                        "bling_order_number": local.get("numero_pedido"),
                    }
            except Exception as exc:
                logger.warning("[marketplace-webhook] falha lookup local Bling numeroLoja=%s: %s", external_order_id, exc)
        data_compra_marketplace = data_venda
        data_pagamento_marketplace = None
        data_envio_marketplace = None
        payment_time_source = None
        # Canonizacao logistica: prazo de postagem, modalidade e identidade do
        # comprador. Antes isto era `if "entrega rapida" in carrier` inline aqui,
        # e o resultado nem chegava a ser gravado — `modalidade` era calculada,
        # usada para o calculo de coleta e descartada. Dai `modalidade_logistica`,
        # `data_limite_envio` e `buyer_username` estarem zerados em producao.
        logistica = logistics_canonicalization.resolve(source, details)
        modalidade = logistica.modalidade_logistica

        if source == "shopee":
            data_compra_marketplace = (details or {}).get("create_time") or data_venda
            if (details or {}).get("pay_time"):
                data_pagamento_marketplace = (details or {}).get("pay_time")
                payment_time_source = "shopee.pay_time"
            raw = (details or {}).get("raw") or {}
            data_envio_marketplace = (details or {}).get("ship_time") or unix_to_app_iso(raw.get("ship_time"))
            logger.info(
                "[marketplace-webhook] shopee resolve timestamps order_sn=%s status=%s source=%s resolved=%s",
                external_order_id,
                status_original,
                payment_time_source,
                _summarize_timestamps(
                    data_compra_marketplace,
                    data_pagamento_marketplace,
                    data_envio_marketplace,
                    status_original,
                ),
            )
        elif source == "mercadolivre":
            order = (details or {}).get("order") or {}
            data_compra_marketplace = order.get("date_created") or data_venda
            if _meli_date_approved(order):
                data_pagamento_marketplace = _meli_date_approved(order)
                payment_time_source = "mercadolivre.payments.date_approved"
            data_envio_marketplace = order.get("date_closed")
            logger.info(
                "[marketplace-webhook] meli resolve timestamps order_id=%s status=%s source=%s resolved=%s",
                external_order_id,
                status_original,
                payment_time_source,
                _summarize_timestamps(
                    data_compra_marketplace,
                    data_pagamento_marketplace,
                    data_envio_marketplace,
                    status_original,
                ),
            )

        coleta_contexto = logistica_coleta_service.calcular_data_coleta(
            marketplace_integration_id=marketplace_integration_id,
            modalidade=modalidade,
            pagamento_dt=_parse_datetime(data_pagamento_marketplace),
            compra_dt=_parse_datetime(data_compra_marketplace),
        )
        logger.info(
            "[marketplace-webhook] coleta calculada source=%s external_order_id=%s modalidade=%s "
            "prazo_postagem=%s (%s) motivo=%s contexto=%s",
            source,
            external_order_id,
            modalidade,
            logistica.data_limite_envio,
            logistica.dispatch_deadline_source or "nao informado",
            logistica.reason,
            {
                "data_coleta": coleta_contexto.get("data_coleta"),
                "horario_corte": coleta_contexto.get("horario_corte"),
                "horario_coleta": coleta_contexto.get("horario_coleta"),
                "regra_id": (coleta_contexto.get("regra") or {}).get("id"),
                "regra_modalidade": (coleta_contexto.get("regra") or {}).get("modalidade"),
            },
        )
        status_original = self._sanitize_status_original(status_original)

        row = {
            "numero_pedido": str(external_order_id),
            "codigo_pedido_externo": str(external_order_id),
            "origem": source.upper(),
            "marketplace_module_id": source,
            "marketplace_integration_id": marketplace_integration_id,
            "erp_integration_id": bling_integration_id,
            "erp_store_id": str(bling_loja_id) if bling_loja_id not in (None, "") else None,
            "erp_order_id": bling_ref.get("bling_order_id"),
            "erp_order_number": bling_ref.get("bling_order_number"),
            "canal_venda_id": channel_id,
            # Congelado na ingestao de proposito: trocar o modo do vinculo
            # (migrar a conta do ERP para o marketplace direto) passa a valer
            # para pedidos novos, sem mudar retroativamente quem tem autoridade
            # sobre os que ja estao em transito.
            "ingest_origin_mode": ingest_origin_mode,
            "situacao_pedido_id": situacao_pedido_id,
            "status_original": status_original,
            "informacoes_cliente": raw_customer or {},
            "cliente_nome": self._customer_name(raw_customer),
            "total_pedido": total,
            "moeda": currency or "BRL",
            "data_venda": data_venda,
            "data_compra_marketplace": data_compra_marketplace,
            "data_pagamento_marketplace": data_pagamento_marketplace,
            "data_coleta": coleta_contexto.get("data_coleta"),
            "data_envio_marketplace": data_envio_marketplace,
            "regra_logistica_integracao_id": (coleta_contexto.get("regra") or {}).get("id"),
            "marketplace_order_id": str(external_order_id),
            "pedido_bling_id": bling_ref.get("pedido_bling_id"),
            "ingest_source": source,
            "message_to_seller": (details or {}).get("message_to_seller"),
            "updated_at": get_now_iso(),
            # Campos logisticos canonicos: prazo de POSTAGEM (nao de entrega),
            # modalidade e identidade do comprador.
            **logistica.to_order_fields(),
            **{key: value for key, value in mirror_fields.items() if value is not None},
        }
        row = {key: value for key, value in row.items() if value is not None}

        if source == "shopee":
            snapshot_items = self._normalize_shopee_items(details or {})
            snapshot_logistics = {
                "shipping_carrier": (details or {}).get("shipping_carrier"),
                "service": (details or {}).get("shipping_carrier"),
                "package_list": (details or {}).get("package_list"),
                "ship_by_date": (details or {}).get("ship_by_date"),
                "address": (details or {}).get("recipient_address"),
            }
        else:
            order_detail = (details or {}).get("order") or {}
            shipment = (details or {}).get("shipment") or {}
            snapshot_items = self._normalize_meli_items(order_detail)
            snapshot_logistics = {
                "shipment_id": (order_detail.get("shipping") or {}).get("id") or shipment.get("id"),
                "shipping_status": shipment.get("status"),
                "shipping_carrier": shipment.get("mode"),
                "address": shipment.get("receiver_address"),
            }
        snapshot_logistics.update({
            "purchase_at": data_compra_marketplace,
            "payment_at": data_pagamento_marketplace,
            "collection_at": coleta_contexto.get("data_coleta"),
            "marketplace_shipped_at": data_envio_marketplace,
            "cutoff_time": coleta_contexto.get("horario_corte"),
            "collection_time": coleta_contexto.get("horario_coleta"),
            "rule_id": (coleta_contexto.get("regra") or {}).get("id"),
            "payment_time_source": payment_time_source,
        })
        snapshot = {
            "identity": {
                "ingest_source": source,
                "ingest_origin_mode": ingest_origin_mode,
                "marketplace": source,
                "marketplace_order_id": str(external_order_id),
                "marketplace_integration_id": marketplace_integration_id,
                "erp_integration_id": bling_integration_id,
                "erp_order_id": bling_ref.get("bling_order_id"),
                "erp_order_number": bling_ref.get("bling_order_number"),
            },
            "customer": raw_customer or {},
            "items": snapshot_items,
            "logistics": snapshot_logistics,
            "financial": {"total": total, "currency": currency or "BRL"},
            "platform_fields": {source: details or {}, **mirror_fields},
            "raw_refs": {source: details or {}, "bling_lookup": bling_ref},
            "source_history": [{"source": source, "at": get_now_iso()}],
        }
        refs = [
            {
                "integration_id": marketplace_integration_id,
                "module_id": source,
                "role": "sales_origin",
                "external_order_id": str(external_order_id),
                "external_status": status_original,
            },
        ]
        if lifecycle_event:
            transition = canonical_order_repository.apply_marketplace_event(
                row,
                lifecycle_event=lifecycle_event,
                snapshot=snapshot,
                refs=refs,
                projection_enabled=str(
                    os.getenv("MARKETPLACE_LIFECYCLE_PROJECTION_ENABLED", "false")
                ).strip().lower() in ("1", "true", "yes", "on"),
            )
            pedido_id = int(transition["pedido_id"])
        else:
            pedido_id = canonical_order_repository.upsert(row, snapshot=snapshot, refs=refs)
        if not (
            bling_ref.get("bling_order_id")
            and bling_ref.get("bling_order_number")
        ):
            canonical_order_repository.defer_unresolved_erp_order(
                pedido_id=pedido_id,
                erp_integration_id=bling_integration_id,
                erp_store_id=bling_loja_id,
                erp_order_id=None,
                marketplace_order_id=external_order_id,
                marketplace_module_id=source,
                payload={"marketplace_module_id": source, "marketplace_integration_id": marketplace_integration_id},
                reason="erp_reference_pending",
            )
        canonical_order_repository.apply_pending_erp_reference_for_order(
            pedido_id=pedido_id,
            marketplace_module_id=source,
            marketplace_order_id=external_order_id,
        )
        persist_classification_from_payload(
            {"numeroLoja": str(external_order_id), "itens": snapshot_items},
            pedido_id,
            log=logger,
        )
        # Classificacao de modalidade logistica (spec: docs/specs/02-domains/despacho).
        # Roda em paralelo com `logistics_canonicalization` acima (que resolve
        # is_flex/modalidade_logistica legado): esta chamada popula o catalogo
        # novo (metodo_envio_chave/rotulo, modalidade_logistica_id,
        # compromisso_logistico_em) sem que um dependa do outro. Nunca lanca
        # excecao — falha aqui nunca pode derrubar o ingest do pedido.
        try:
            classify_modalidade_logistica(
                pedido_id=pedido_id,
                module_id=source,
                integration_id=marketplace_integration_id,
                detail=details,
            )
        except Exception:
            logger.warning(
                "[marketplace-webhook] falha ao classificar modalidade logistica pedido_id=%s source=%s",
                pedido_id, source, exc_info=True,
            )
        return pedido_id

    def _customer_name(self, customer: dict | None) -> str | None:
        if not isinstance(customer, dict):
            return None
        if customer.get("nickname"):
            return customer.get("nickname")
        if customer.get("buyer_username"):
            return customer.get("buyer_username")
        if customer.get("username"):
            return customer.get("username")
        first = customer.get("first_name")
        last = customer.get("last_name")
        return " ".join(part for part in (first, last) if part) or None

    def _shopee_customer(self, detail: dict) -> dict:
        address = detail.get("recipient_address") or {}
        return {
            "name": address.get("name") or detail.get("buyer_username"),
            "phone": address.get("phone"),
            "username": detail.get("buyer_username"),
            "buyer_username": detail.get("buyer_username"),
            "buyer_user_id": detail.get("buyer_user_id"),
            "address": address,
        }

    def _meli_customer(self, order: dict) -> dict:
        buyer = order.get("buyer") or {}
        return {
            "name": buyer.get("nickname") or " ".join(part for part in (buyer.get("first_name"), buyer.get("last_name")) if part),
            "nickname": buyer.get("nickname"),
            "buyer_user_id": buyer.get("id"),
            "raw": buyer,
        }

    def _write_snapshot_for_marketplace(
        self,
        *,
        source: str,
        pedido_id: int | None,
        external_order_id: str,
        marketplace_integration_id: int | None,
        bling_integration_id: int | None,
        bling_order_id: Any = None,
        bling_order_number: Any = None,
        customer: dict,
        total: Any,
        currency: str,
        details: dict,
        mirror_fields: dict,
    ) -> None:
        if not pedido_id:
            return

        if source == "shopee":
            items = self._normalize_shopee_items(details)
            logistics = {
                "shipping_carrier": details.get("shipping_carrier"),
                "service": details.get("shipping_carrier"),
                "is_fulfillment": str(details.get("fulfillment_flag") or "").lower() in ("fulfilled_by_shopee", "true", "full"),
                "fulfillment_flag": details.get("fulfillment_flag"),
                "package_list": details.get("package_list"),
                "ship_by_date": details.get("ship_by_date"),
                "purchase_at": mirror_fields.get("data_compra_marketplace"),
                "payment_at": mirror_fields.get("data_pagamento_marketplace"),
                "collection_at": mirror_fields.get("data_coleta"),
                "marketplace_shipped_at": mirror_fields.get("data_envio_marketplace"),
                "cutoff_time": mirror_fields.get("horario_corte"),
                "collection_time": mirror_fields.get("horario_coleta"),
                "rule_id": mirror_fields.get("regra_logistica_integracao_id"),
                "payment_time_source": mirror_fields.get("payment_time_source"),
                "address": details.get("recipient_address"),
            }
            platform_fields = {
                "buyer_username": details.get("buyer_username"),
                "buyer_user_id": details.get("buyer_user_id"),
                "message_to_seller": (details.get("raw") or {}).get("message_to_seller"),
                "shipping_carrier": details.get("shipping_carrier"),
                "shopee": details,
            }
        else:
            order = details.get("order") or {}
            shipment = details.get("shipment") or {}
            sla = details.get("sla") or {}
            items = self._normalize_meli_items(order)
            logistics = {
                "shipment_id": (order.get("shipping") or {}).get("id") or shipment.get("id"),
                "shipping_status": shipment.get("status"),
                "shipping_carrier": shipment.get("mode"),
                "service": shipment.get("shipping_option", {}).get("name") if isinstance(shipment.get("shipping_option"), dict) else None,
                "expected_date": sla.get("expected_date"),
                "purchase_at": mirror_fields.get("data_compra_marketplace"),
                "payment_at": mirror_fields.get("data_pagamento_marketplace"),
                "collection_at": mirror_fields.get("data_coleta"),
                "marketplace_shipped_at": mirror_fields.get("data_envio_marketplace"),
                "cutoff_time": mirror_fields.get("horario_corte"),
                "collection_time": mirror_fields.get("horario_coleta"),
                "rule_id": mirror_fields.get("regra_logistica_integracao_id"),
                "payment_time_source": mirror_fields.get("payment_time_source"),
                "address": shipment.get("receiver_address"),
            }
            platform_fields = {
                "buyer_username": (order.get("buyer") or {}).get("nickname"),
                "mercadolivre": details,
            }

        canonical_order_snapshot_service.upsert_snapshot(
            pedido_id=pedido_id,
            ingest_source=source,
            marketplace=source,
            marketplace_order_id=external_order_id,
            marketplace_integration_id=marketplace_integration_id,
            bling_integration_id=bling_integration_id,
            bling_order_id=bling_order_id,
            bling_order_number=bling_order_number,
            customer=customer,
            items=items,
            logistics=logistics,
            financial={"total": total, "currency": currency or "BRL"},
            platform_fields=platform_fields,
            raw_refs={**mirror_fields, source: details},
            upsert_items=True,
        )
        persist_classification_from_payload(
            {
                "numeroLoja": external_order_id,
                "itens": items,
            },
            pedido_id,
            log=logger,
        )

    def _lookup_bling_order(self, *, bling_integration_id: int | None, external_order_id: str) -> dict:
        result = {
            "status": "not_found",
            "numero_loja": external_order_id,
            "bling_integration_id": bling_integration_id,
        }
        if not bling_integration_id or not external_order_id:
            return result
        local_error = None
        try:
            rows = (
                supabase_db.table("pedidos_bling")
                .select("id,bling_id,numero_pedido,numero_loja")
                .eq("bling_integration_id", bling_integration_id)
                .eq("numero_loja", str(external_order_id))
                .limit(1)
                .execute()
                .data
                or []
            )
            if rows:
                row = rows[0]
                return {
                    **result,
                    "status": "found",
                    "pedido_bling_id": row.get("id"),
                    "bling_order_id": row.get("bling_id"),
                    "bling_order_number": row.get("numero_pedido"),
                }
        except Exception as exc:
            logger.warning("[marketplace-ingest] erro ao buscar pedido Bling por numero_loja=%s: %s", external_order_id, exc)
            local_error = str(exc)

        remote = self._lookup_bling_order_remote(
            bling_integration_id=bling_integration_id,
            external_order_id=external_order_id,
        )
        if remote:
            if remote.get('status') == 'error':
                return {**result, **remote}
            return {**result, **remote}

        if local_error:
            result["status"] = "error"
            result["error"] = local_error
        return result

    def _lookup_bling_order_remote(self, *, bling_integration_id: int, external_order_id: str) -> dict | None:
        try:
            from nistiprint_shared.services.bling.bling_client import (
                BlingClient,
                BlingRateLimitedError,
                BlingTransientHTTPError,
            )

            client = BlingClient.create_client_for_integration_id(int(bling_integration_id))
            matches = client.get_order_numbers_by_store_numbers([str(external_order_id)]) or []
        except BlingRateLimitedError as exc:
            logger.warning(
                "[marketplace-ingest] rate limit ao consultar Bling API por numeroLoja=%s integration_id=%s retry_after=%s",
                external_order_id,
                bling_integration_id,
                exc.retry_after,
            )
            return {
                "status": "error",
                "reason": "bling_rate_limited",
                "error": str(exc),
                "retry_after": exc.retry_after,
            }
        except BlingTransientHTTPError as exc:
            logger.warning(
                "[marketplace-ingest] Bling temporariamente indisponivel numeroLoja=%s integration_id=%s retry_after=%s",
                external_order_id,
                bling_integration_id,
                exc.retry_after,
            )
            return {
                "status": "error",
                "reason": "bling_lookup_transient_error",
                "error": str(exc),
                "retry_after": exc.retry_after,
            }
        except Exception as exc:
            logger.warning(
                "[marketplace-ingest] erro ao consultar Bling API por numeroLoja=%s integration_id=%s: %s",
                external_order_id,
                bling_integration_id,
                exc,
            )
            return None

        for match in matches:
            if str(match.get("numeroLoja") or "") != str(external_order_id):
                continue
            logger.info(
                "[marketplace-ingest] pedido Bling resolvido via API numeroLoja=%s numero=%s id=%s",
                external_order_id,
                match.get("numero"),
                match.get("id"),
            )
            return {
                "status": "found",
                "resolved_via": "bling_api",
                "pedido_bling_id": None,
                "bling_order_id": match.get("id"),
                "bling_order_number": match.get("numero"),
            }
        return None

    def _normalize_shopee_items(self, detail: dict) -> list[dict]:
        rows = []
        for item in detail.get("item_list") or []:
            quantity = item.get("model_quantity_purchased") or item.get("quantity") or 1
            price = item.get("model_discounted_price") or item.get("model_original_price") or item.get("item_price")
            rows.append({
                "sku": item.get("model_sku") or item.get("item_sku"),
                "name": item.get("item_name") or item.get("model_name"),
                "quantity": quantity,
                "unit_price": price,
                "subtotal": float(quantity or 0) * float(price or 0) if price is not None else None,
                "raw": item,
            })
        return rows

    def _normalize_meli_items(self, order: dict) -> list[dict]:
        rows = []
        for item in order.get("order_items") or []:
            item_info = item.get("item") or {}
            quantity = item.get("quantity") or 1
            price = item.get("unit_price")
            rows.append({
                "sku": item_info.get("seller_sku") or item_info.get("id"),
                "name": item_info.get("title"),
                "quantity": quantity,
                "unit_price": price,
                "subtotal": float(quantity or 0) * float(price or 0) if price is not None else None,
                "raw": item,
            })
        return rows

    def _update_webhook_event_from_result(self, webhook_event_id: int | None, result: dict):
        if not webhook_event_id:
            return
        fields = {
            "pedido_id": result.get("pedido_id"),
            "numero_loja": result.get("external_order_id"),
            "resolved_order_id": result.get("external_order_id"),
            "resolved_order_ids": result.get("resolved_order_ids"),
            "provider_topic": result.get("provider_topic"),
            "provider_resource": result.get("provider_resource"),
            "provider_resource_type": result.get("provider_resource_type"),
            "provider_resource_id": result.get("provider_resource_id"),
            "resolution_status": result.get("resolution_status"),
            "provider_updated_at": result.get("provider_updated_at"),
            "lifecycle_stage": result.get("lifecycle_stage"),
            "last_status": result.get("event_status") or result.get("status"),
            "last_attempt_at": get_now_iso(),
            # Sem isto, a unica pista da conta em `webhook_events` e o
            # `dedupe_scope`, que guarda o identificador da conta por acidente de
            # projeto. Com duas contas na mesma origem, filtrar backlog e falha
            # por conta passa a ser rotina.
            "marketplace_integration_id": result.get("marketplace_integration_id"),
        }
        fields = {key: value for key, value in fields.items() if value is not None}
        if not fields:
            return
        try:
            supabase_db.table("webhook_events").update(fields).eq("id", webhook_event_id).execute()
        except Exception as exc:
            logger.warning("[marketplace-ingest] erro ao atualizar webhook_events id=%s: %s", webhook_event_id, exc)

    def _write_ingest_log(
        self,
        *,
        correlation_id: str,
        stage: str,
        status: str | None,
        message: str | None,
        duration_ms: int | None,
        payload_summary: dict | None,
        pedido_id: int | None = None,
        marketplace_integration_id: int | None = None,
    ):
        try:
            supabase_db.table("pedido_ingest_log").insert({
                "correlation_id": correlation_id,
                "stage": stage,
                "status": status,
                "message": message,
                "duration_ms": duration_ms,
                "payload_summary": payload_summary,
                "pedido_id": pedido_id,
                "marketplace_integration_id": marketplace_integration_id,
            }).execute()
        except Exception as exc:
            logger.warning("[marketplace-ingest] erro ao gravar pedido_ingest_log stage=%s: %s", stage, exc)


marketplace_webhook_ingest_service = MarketplaceWebhookIngestService()
