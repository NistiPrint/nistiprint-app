import logging
import traceback
from datetime import datetime
from time import perf_counter
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.canonical_order_status_service import (
    canonical_order_status_service,
)
from nistiprint_shared.services.canonical_order_snapshot_service import (
    canonical_order_snapshot_service,
)
from nistiprint_shared.services.correlation_service import generate_correlation_id, set_correlation_id
from nistiprint_shared.services.logistica_coleta_service import logistica_coleta_service
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver
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
    return resource.rstrip("/").split(marker)[-1].strip("/") or None


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
                result = self._process_shopee(payload, correlation_id=correlation_id)
            else:
                result = self._process_mercadolivre(payload, correlation_id=correlation_id)

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

    def _process_shopee(self, payload: dict, *, correlation_id: str) -> dict:
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        order_sn = _first_present(
            body.get("order_sn"),
            body.get("ordersn"),
            body.get("order_id"),
            ((body.get("orders") or [{}])[0] or {}).get("order_sn") if isinstance(body.get("orders"), list) and body.get("orders") else None,
        )
        shop_id = _first_present(body.get("shop_id"), body.get("shopid"), payload.get("shop_id"))

        if not order_sn:
            return {
                "status": "error",
                "error_type": "missing_order_id",
                "message": "Webhook Shopee sem order_sn",
            }

        marketplace_inst = self._find_marketplace_integration("shopee", shop_id=shop_id)
        if not marketplace_inst:
            return {
                "status": "error",
                "error_type": "marketplace_integration_not_found",
                "message": f"Integracao Shopee nao encontrada para shop_id={shop_id}",
                "external_order_id": str(order_sn),
            }

        link = self._find_channel_connection(marketplace_inst.get("id"))
        inactive = self._inactive_source_result("shopee", link, str(order_sn), marketplace_inst)
        if inactive:
            return inactive

        detail = self._fetch_shopee_detail(marketplace_inst, str(order_sn))
        if detail.get("error"):
            logger.warning(
                "[marketplace-webhook] shopee detail unavailable order_sn=%s integration_id=%s error=%s",
                order_sn,
                marketplace_inst.get("id"),
                detail.get("error"),
            )
            return {
                "status": "error",
                "error_type": "shopee_detail_unavailable",
                "message": detail.get("error"),
                "external_order_id": str(order_sn),
                "marketplace_integration_id": marketplace_inst.get("id"),
            }

        logger.info(
            "[marketplace-webhook] shopee detail fetched order_sn=%s status=%s keys=%s",
            order_sn,
            detail.get("order_status"),
            sorted(detail.keys()),
        )

        pedido_shopee_id = self._upsert_shopee_mirror(detail, marketplace_inst.get("id"))
        status = canonical_order_status_service.resolve_shopee(
            detail.get("order_status") or body.get("order_status"),
            integration_id=marketplace_inst.get("id"),
        )
        pedido_id = self._upsert_pedido_status(
            source="shopee",
            external_order_id=str(order_sn),
            marketplace_integration_id=marketplace_inst.get("id"),
            bling_integration_id=(link or {}).get("bling_integration_id"),
            channel_id=(link or {}).get("channel_id"),
            situacao_pedido_id=status.internal_situacao_pedido_id,
            status_original=detail.get("order_status") or body.get("order_status"),
            mirror_fields={"pedido_shopee_id": pedido_shopee_id},
            raw_customer=self._shopee_customer(detail),
            total=detail.get("total"),
            currency=detail.get("currency") or "BRL",
            data_venda=detail.get("create_time"),
            details=detail,
        )
        logger.info(
            "[marketplace-webhook] shopee timestamps order_sn=%s %s",
            order_sn,
            _summarize_timestamps(
                data_compra=detail.get("create_time"),
                data_pagamento=detail.get("pay_time"),
                data_envio=detail.get("ship_time"),
                status=detail.get("order_status"),
            ),
        )

        return {
            "status": "success",
            "message": f"Pedido Shopee {order_sn} atualizado",
            "pedido_id": pedido_id,
            "external_order_id": str(order_sn),
            "marketplace_integration_id": marketplace_inst.get("id"),
            "internal_situacao_pedido_id": status.internal_situacao_pedido_id,
            "external_status_id": status.external_status_id,
        }

    def _process_mercadolivre(self, payload: dict, *, correlation_id: str) -> dict:
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        resource = str(body.get("resource") or "")
        order_id = _first_present(
            body.get("order_id"),
            body.get("id") if str(body.get("topic") or "").endswith("orders") else None,
            _extract_resource_id(resource, "/orders/"),
        )
        shipment_id = _first_present(body.get("shipment_id"), _extract_resource_id(resource, "/shipments/"))
        payment_id = _first_present(body.get("payment_id"), _extract_resource_id(resource, "/payments/"))
        seller_id = _first_present(body.get("user_id"), body.get("seller_id"), body.get("application_id"))

        marketplace_inst = self._find_marketplace_integration("mercadolivre", shop_id=seller_id)
        if not marketplace_inst:
            return {
                "status": "error",
                "error_type": "marketplace_integration_not_found",
                "message": f"Integracao Mercado Livre nao encontrada para seller/user={seller_id}",
                "external_order_id": str(order_id),
            }

        integration = self._meli_integration(marketplace_inst)
        derived_payment_status = None
        derived_shipping_status = None
        if not order_id and shipment_id:
            shipment = meli_driver.get_shipment(integration, str(shipment_id))
            if shipment and not shipment.get("error"):
                order_id = _first_present(
                    shipment.get("order_id"),
                    (shipment.get("order") or {}).get("id") if isinstance(shipment.get("order"), dict) else None,
                )
                derived_shipping_status = shipment.get("status")
        if not order_id and payment_id:
            payment = meli_driver.get_payment(integration, str(payment_id))
            if payment and not payment.get("error"):
                order_id = _first_present(
                    (payment.get("order") or {}).get("id") if isinstance(payment.get("order"), dict) else None,
                    payment.get("order_id"),
                    payment.get("external_reference"),
                )
                derived_payment_status = payment.get("status")

        if not order_id:
            return {
                "status": "error",
                "error_type": "missing_order_id",
                "message": "Webhook Mercado Livre sem order_id/resource derivavel",
                "marketplace_integration_id": marketplace_inst.get("id"),
            }

        link = self._find_channel_connection(marketplace_inst.get("id"))
        inactive = self._inactive_source_result("mercadolivre", link, str(order_id), marketplace_inst)
        if inactive:
            return inactive

        detail = self._fetch_meli_detail(marketplace_inst, str(order_id))
        if detail.get("error"):
            logger.warning(
                "[marketplace-webhook] meli detail unavailable order_id=%s integration_id=%s error=%s",
                order_id,
                marketplace_inst.get("id"),
                detail.get("error"),
            )
            return {
                "status": "error",
                "error_type": "mercadolivre_detail_unavailable",
                "message": detail.get("error"),
                "external_order_id": str(order_id),
                "marketplace_integration_id": marketplace_inst.get("id"),
            }

        logger.info(
            "[marketplace-webhook] meli detail fetched order_id=%s order_keys=%s shipment_keys=%s",
            order_id,
            sorted((detail.get("order") or {}).keys()),
            sorted((detail.get("shipment") or {}).keys()),
        )

        pedido_meli_id = self._upsert_meli_mirror(detail, marketplace_inst.get("id"))
        order = detail.get("order") or {}
        shipment = detail.get("shipment") or {}
        payment = (order.get("payments") or [{}])[0] if isinstance(order.get("payments"), list) else {}
        payment_status = _first_present(body.get("payment_status"), derived_payment_status, payment.get("status"), order.get("status"))
        shipping_status = _first_present(body.get("shipping_status"), derived_shipping_status, shipment.get("status"))
        status = canonical_order_status_service.resolve_mercadolivre(
            payment_status=payment_status,
            shipping_status=shipping_status,
            integration_id=marketplace_inst.get("id"),
        )
        pedido_id = self._upsert_pedido_status(
            source="mercadolivre",
            external_order_id=str(order_id),
            marketplace_integration_id=marketplace_inst.get("id"),
            bling_integration_id=(link or {}).get("bling_integration_id"),
            channel_id=(link or {}).get("channel_id"),
            situacao_pedido_id=status.internal_situacao_pedido_id,
            status_original=f"payment:{payment_status or '-'}|shipping:{shipping_status or '-'}",
            mirror_fields={"pedido_mercadolivre_id": pedido_meli_id},
            raw_customer=self._meli_customer(order),
            total=order.get("total_amount"),
            currency=order.get("currency_id") or "BRL",
            data_venda=order.get("date_created"),
            details=detail,
        )
        logger.info(
            "[marketplace-webhook] meli timestamps order_id=%s %s",
            order_id,
            _summarize_timestamps(
                data_compra=order.get("date_created"),
                data_pagamento=_meli_date_approved(order),
                data_envio=order.get("date_closed"),
                status=order.get("status"),
            ),
        )

        return {
            "status": "success",
            "message": f"Pedido Mercado Livre {order_id} atualizado",
            "pedido_id": pedido_id,
            "external_order_id": str(order_id),
            "marketplace_integration_id": marketplace_inst.get("id"),
            "internal_situacao_pedido_id": status.internal_situacao_pedido_id,
            "external_status_id": status.external_status_id,
            "status_domain": status.status_domain,
        }

    def _inactive_source_result(self, source: str, link: dict | None, external_order_id: str, marketplace_inst: dict) -> dict | None:
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
        if link.get("process_webhooks") is False or ingest_origin_mode != "marketplace_direct":
            return {
                "status": "skipped",
                "event_status": "skipped_inactive_source",
                "skip_reason": "inactive_source",
                "message": (
                    f"Webhook {source} ignorado: ingest_origin_mode={ingest_origin_mode} "
                    f"process_webhooks={link.get('process_webhooks')}"
                ),
                "external_order_id": external_order_id,
                "marketplace_integration_id": marketplace_inst.get("id"),
            }
        return None

    def _find_marketplace_integration(self, module_id: str, *, shop_id: Any = None) -> dict | None:
        rows = (
            supabase_db.table("installed_integrations")
            .select("*")
            .eq("module_id", module_id)
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        if not rows:
            return None

        normalized_shop_id = str(shop_id or "").strip()
        if normalized_shop_id:
            for row in rows:
                cfg = row.get("config") or {}
                candidates = [
                    cfg.get("shop_id"),
                    cfg.get("seller_id"),
                    cfg.get("user_id"),
                    cfg.get("bling_loja_id"),
                ]
                candidates.extend(cfg.get("shop_ids") or [])
                if normalized_shop_id in {str(candidate).strip() for candidate in candidates if candidate not in (None, "")}:
                    return row

        non_dummy = [row for row in rows if not (row.get("config") or {}).get("dummy")]
        if len(non_dummy) == 1:
            return non_dummy[0]
        return rows[0] if len(rows) == 1 else None

    def _find_channel_connection(self, marketplace_integration_id: int | None) -> dict | None:
        if not marketplace_integration_id:
            return None
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

    def _fetch_shopee_detail(self, marketplace_inst: dict, order_sn: str) -> dict:
        credentials = marketplace_inst.get("credentials") or {}
        integration = {
            "config": marketplace_inst.get("config") or {},
            "credentials": credentials,
            "access_token": marketplace_inst.get("access_token") or credentials.get("access_token"),
        }
        return shopee_driver.get_order_detail(integration, [order_sn])

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
        return {
            "config": marketplace_inst.get("config") or {},
            "credentials": credentials,
            "access_token": marketplace_inst.get("access_token") or credentials.get("access_token"),
        }

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

    def _upsert_pedido_status(
        self,
        *,
        source: str,
        external_order_id: str,
        marketplace_integration_id: int | None,
        bling_integration_id: int | None,
        channel_id: int | None,
        situacao_pedido_id: int | None,
        status_original: str | None,
        mirror_fields: dict,
        raw_customer: dict | None,
        total: Any,
        currency: str,
        data_venda: str | None,
        details: dict | None = None,
    ) -> int | None:
        if not external_order_id:
            return None

        bling_ref = self._lookup_bling_order(
            bling_integration_id=bling_integration_id,
            external_order_id=str(external_order_id),
        )
        data_compra_marketplace = data_venda
        data_pagamento_marketplace = data_venda
        data_envio_marketplace = None
        payment_time_source = "fallback.data_compra_marketplace" if data_venda else None
        modalidade = "STANDARD"
        if source == "shopee":
            data_compra_marketplace = (details or {}).get("create_time") or data_venda
            if (details or {}).get("pay_time"):
                data_pagamento_marketplace = (details or {}).get("pay_time")
                payment_time_source = "shopee.pay_time"
            raw = (details or {}).get("raw") or {}
            data_envio_marketplace = (details or {}).get("ship_time") or unix_to_app_iso(raw.get("ship_time"))
            carrier = str((details or {}).get("shipping_carrier") or "").lower()
            if "entrega rápida" in carrier or "entrega rapida" in carrier:
                modalidade = "FLEX"
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
            shipment = (details or {}).get("shipment") or {}
            data_compra_marketplace = order.get("date_created") or data_venda
            if _meli_date_approved(order):
                data_pagamento_marketplace = _meli_date_approved(order)
                payment_time_source = "mercadolivre.payments.date_approved"
            data_envio_marketplace = order.get("date_closed")
            option = shipment.get("shipping_option") if isinstance(shipment.get("shipping_option"), dict) else {}
            logistic_type = str(shipment.get("logistic_type") or shipment.get("shipping_type") or "").lower()
            option_name = str(option.get("name") or "").lower()
            if logistic_type == "self_service" and option_name in ("prioritario", "flex"):
                modalidade = "FLEX"
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
            "[marketplace-webhook] coleta calculada source=%s external_order_id=%s modalidade=%s contexto=%s",
            source,
            external_order_id,
            modalidade,
            {
                "data_coleta": coleta_contexto.get("data_coleta"),
                "horario_corte": coleta_contexto.get("horario_corte"),
                "horario_coleta": coleta_contexto.get("horario_coleta"),
                "regra_id": (coleta_contexto.get("regra") or {}).get("id"),
                "regra_modalidade": (coleta_contexto.get("regra") or {}).get("modalidade"),
            },
        )
        row = {
            "numero_pedido": f"{source.upper()}-{external_order_id}",
            "codigo_pedido_externo": str(external_order_id),
            "origem": source.upper(),
            "marketplace_integration_id": marketplace_integration_id,
            "bling_integration_id": bling_integration_id,
            "canal_venda_id": channel_id,
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
            "bling_order_id": bling_ref.get("bling_order_id"),
            "bling_order_number": bling_ref.get("bling_order_number"),
            "ingest_source": source,
            "updated_at": get_now_iso(),
            **{key: value for key, value in mirror_fields.items() if value is not None},
        }
        row = {key: value for key, value in row.items() if value is not None}

        existing = self._find_existing_pedido(
            external_order_id=external_order_id,
            marketplace_integration_id=marketplace_integration_id,
        )
        if existing:
            response = supabase_db.table("pedidos").update(row).eq("id", existing["id"]).execute()
            pedido_id = (response.data or [{}])[0].get("id") or existing["id"]
        else:
            response = supabase_db.table("pedidos").insert(row).execute()
            pedido_id = (response.data or [{}])[0].get("id")

        self._write_snapshot_for_marketplace(
            source=source,
            pedido_id=pedido_id,
            external_order_id=str(external_order_id),
            marketplace_integration_id=marketplace_integration_id,
            bling_integration_id=bling_integration_id,
            bling_order_id=bling_ref.get("bling_order_id"),
            bling_order_number=bling_ref.get("bling_order_number"),
            customer=raw_customer or {},
            total=total,
            currency=currency,
            details=details or {},
            mirror_fields={
                **mirror_fields,
                "bling_lookup": bling_ref,
                "data_compra_marketplace": data_compra_marketplace,
                "data_pagamento_marketplace": data_pagamento_marketplace,
                "data_coleta": coleta_contexto.get("data_coleta"),
                "data_envio_marketplace": data_envio_marketplace,
                "regra_logistica_integracao_id": (coleta_contexto.get("regra") or {}).get("id"),
                "horario_corte": coleta_contexto.get("horario_corte"),
                "horario_coleta": coleta_contexto.get("horario_coleta"),
                "payment_time_source": payment_time_source,
            },
        )
        return pedido_id

    def _find_existing_pedido(self, *, external_order_id: str, marketplace_integration_id: int | None) -> dict | None:
        query = (
            supabase_db.table("pedidos")
            .select("id")
            .eq("marketplace_order_id", str(external_order_id))
        )
        if marketplace_integration_id:
            query = query.eq("marketplace_integration_id", marketplace_integration_id)
        rows = query.limit(1).execute().data or []
        if rows:
            return rows[0]

        if marketplace_integration_id:
            rows = (
                supabase_db.table("pedidos")
                .select("id")
                .eq("codigo_pedido_externo", str(external_order_id))
                .eq("marketplace_integration_id", marketplace_integration_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            if rows:
                return rows[0]

        if marketplace_integration_id:
            return None

        rows = (
            supabase_db.table("pedidos")
            .select("id")
            .eq("codigo_pedido_externo", str(external_order_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

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

    def _lookup_bling_order(self, *, bling_integration_id: int | None, external_order_id: str) -> dict:
        result = {
            "status": "not_found",
            "numero_loja": external_order_id,
            "bling_integration_id": bling_integration_id,
        }
        if not bling_integration_id or not external_order_id:
            return result
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
            result["status"] = "error"
            result["error"] = str(exc)
        return result

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
            "last_status": result.get("event_status") or result.get("status"),
            "last_attempt_at": get_now_iso(),
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
            }).execute()
        except Exception as exc:
            logger.warning("[marketplace-ingest] erro ao gravar pedido_ingest_log stage=%s: %s", stage, exc)


marketplace_webhook_ingest_service = MarketplaceWebhookIngestService()
