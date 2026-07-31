"""Provider-specific webhook parsing and order-resource resolution."""
from __future__ import annotations

import re
from typing import Any, Callable

from nistiprint_shared.services.marketplace_contracts import (
    CanonicalOrderSnapshot,
    MarketplaceResourceRef,
    WebhookResolution,
)
from nistiprint_shared.services.marketplace_lifecycle_service import (
    resolve_mercadolivre,
    resolve_shopee,
)
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver


def _body(payload: dict) -> dict:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    return normalized or None


def _numeric_id(value: Any) -> str | None:
    normalized = _text(value)
    return normalized if normalized and normalized.isdigit() else None


class MercadoLivreAdapter:
    provider = "mercadolivre"
    _RESOURCE_RE = re.compile(
        r"^/(?P<kind>orders|shipments|payments|collections|packs)/"
        r"(?P<id>[^/?#]+)(?:[/?#].*)?$"
    )
    _CLAIM_RESOURCE_RE = re.compile(
        r"^/(?:post-purchase/)?v1/claims/(?P<id>[^/?#]+)(?:[/?#].*)?$"
    )
    _TOPIC_RESOURCE = {
        "orders": {"orders"},
        "orders_v2": {"orders"},
        "shipments": {"shipments"},
        "payments": {"payments", "collections"},
    }
    _KIND = {
        "orders": "order",
        "shipments": "shipment",
        "payments": "payment",
        "collections": "collection",
        "packs": "pack",
    }

    def parse_webhook(self, payload: dict) -> WebhookResolution:
        body = _body(payload or {})
        topic = str(body.get("topic") or "").strip().lower()
        resource_path = str(body.get("resource") or "").strip()
        if resource_path and not resource_path.startswith("/"):
            resource_path = f"/{resource_path}"
        if topic == "post_purchase":
            actions = body.get("actions")
            action_set = {
                str(value).strip().lower()
                for value in (actions if isinstance(actions, list) else [actions])
                if value
            }
            match = self._CLAIM_RESOURCE_RE.match(resource_path)
            if not match or not action_set.intersection({"claims", "claims_actions"}):
                return WebhookResolution(
                    self.provider, "unsupported", "unsupported_post_purchase_resource",
                    error_type="unsupported_provider_resource",
                    message="Post Purchase Mercado Livre sem claim tipada",
                )
            claim_id = _numeric_id(match.group("id"))
            if not claim_id:
                return WebhookResolution(
                    self.provider, "invalid", "invalid_resource_id",
                    error_type="invalid_provider_resource_id",
                    message="ID de claim Mercado Livre invalido",
                )
            reference = MarketplaceResourceRef(
                provider=self.provider,
                resource_type="claim",
                resource_id=claim_id,
                resource_path=resource_path,
                account_id=_text(body.get("user_id") or body.get("seller_id")),
                provider_event_id=_text(body.get("_id") or body.get("id")),
                occurred_at=_text(body.get("sent") or body.get("received")),
                topic=topic,
            )
            return WebhookResolution(
                self.provider, "order_event", "parsed", resources=(reference,),
                trace=({"step": "parse", "resource_type": "claim"},),
            )
        if topic not in self._TOPIC_RESOURCE:
            return WebhookResolution(
                self.provider,
                "unsupported",
                "unsupported_topic",
                message=f"Topico Mercado Livre nao suportado: {topic or 'missing'}",
            )
        match = self._RESOURCE_RE.match(resource_path)
        if not match:
            return WebhookResolution(
                self.provider,
                "invalid",
                "invalid_resource",
                error_type="invalid_provider_resource",
                message=f"Resource Mercado Livre invalido para {topic}",
            )
        resource_name = match.group("kind")
        if resource_name not in self._TOPIC_RESOURCE[topic]:
            return WebhookResolution(
                self.provider,
                "invalid",
                "topic_resource_mismatch",
                error_type="provider_topic_resource_mismatch",
                message=f"Topico {topic} incompativel com /{resource_name}",
            )
        resource_id = _numeric_id(match.group("id"))
        if not resource_id:
            return WebhookResolution(
                self.provider,
                "invalid",
                "invalid_resource_id",
                error_type="invalid_provider_resource_id",
                message=f"ID de {resource_name} Mercado Livre invalido",
            )
        reference = MarketplaceResourceRef(
            provider=self.provider,
            resource_type=self._KIND[resource_name],
            resource_id=resource_id,
            resource_path=resource_path,
            account_id=_text(body.get("user_id") or body.get("seller_id")),
            provider_event_id=_text(body.get("_id") or body.get("id")),
            occurred_at=_text(body.get("sent") or body.get("received")),
            topic=topic,
        )
        return WebhookResolution(
            self.provider,
            "order_event",
            "parsed",
            resources=(reference,),
            resolved_order_ids=(resource_id,) if reference.resource_type == "order" else (),
            trace=({"step": "parse", "resource_type": reference.resource_type},),
        )

    def resolve_order_ids(
        self,
        resource: MarketplaceResourceRef,
        integration: dict,
        *,
        payment_lookup: Callable[[str], dict | None] | None = None,
    ) -> WebhookResolution:
        base = WebhookResolution(
            self.provider,
            "order_event",
            "resolving",
            resources=(resource,),
        )
        if resource.resource_type == "order":
            return base.with_orders([resource.resource_id], trace=[{"step": "direct_order"}])

        if resource.resource_type == "claim":
            claim = meli_driver.get_claim(integration, resource.resource_id)
            if claim.get("error"):
                return self._api_failure(base, claim, "claim_resolution_failed")
            claim_resource_type = str(claim.get("resource") or "").strip().lower()
            order_id = _numeric_id(claim.get("resource_id"))
            if claim_resource_type != "order" or not order_id:
                return WebhookResolution(
                    self.provider,
                    "order_event",
                    "unresolved",
                    resources=(resource,),
                    error_type="claim_without_order_reference",
                    message="Claim Mercado Livre nao referencia uma order",
                )
            context = {"claim": claim}
            related_entities = {
                str(value).strip().lower()
                for value in (claim.get("related_entities") or [])
            }
            if "return" in related_entities:
                return_result = meli_driver.get_claim_returns(
                    integration, resource.resource_id
                )
                if isinstance(return_result, dict) and return_result.get("error"):
                    return self._api_failure(
                        base, return_result, "claim_return_resolution_failed"
                    )
                if isinstance(return_result, list):
                    return_result = next(
                        (row for row in return_result if isinstance(row, dict)), {}
                    )
                if isinstance(return_result, dict):
                    context["return"] = return_result
            return WebhookResolution(
                self.provider,
                "order_event",
                "resolving",
                resources=(resource,),
                context=context,
            ).with_orders(
                [order_id],
                trace=[{"step": "claim_order", "claim_id": resource.resource_id}],
            )
        if resource.resource_type == "shipment":
            shipment = meli_driver.get_shipment(integration, resource.resource_id)
            if shipment.get("error"):
                return self._api_failure(base, shipment, "shipment_resolution_failed")
            order_id = _numeric_id(
                shipment.get("order_id")
                or ((shipment.get("order") or {}).get("id")
                    if isinstance(shipment.get("order"), dict) else None)
            )
            if order_id:
                return base.with_orders(
                    [order_id],
                    trace=[{"step": "shipment_order", "shipment_id": resource.resource_id}],
                )
            pack_id = _numeric_id(
                shipment.get("pack_id")
                or ((shipment.get("pack") or {}).get("id")
                    if isinstance(shipment.get("pack"), dict) else None)
            )
            if pack_id:
                pack = meli_driver.get_pack(integration, pack_id)
                if pack.get("error"):
                    return self._api_failure(base, pack, "pack_resolution_failed")
                orders = [
                    value for value in (
                        _numeric_id(row.get("id")) for row in (pack.get("orders") or [])
                        if isinstance(row, dict)
                    ) if value
                ]
                if orders:
                    return base.with_orders(
                        orders,
                        trace=[{"step": "shipment_pack", "pack_id": pack_id}],
                    )
            return WebhookResolution(
                self.provider,
                "order_event",
                "unresolved",
                resources=(resource,),
                error_type="shipment_without_order_reference",
                message="Shipment Mercado Livre sem order ou pack associado",
            )

        if resource.resource_type in {"payment", "collection"}:
            payment = (
                meli_driver.get_collection(integration, resource.resource_id)
                if resource.resource_type == "collection"
                else meli_driver.get_payment(integration, resource.resource_id)
            )
            if payment.get("error"):
                mirrored = payment_lookup(resource.resource_id) if payment_lookup else None
                mirrored_id = _numeric_id((mirrored or {}).get("codigo_pedido"))
                if mirrored_id:
                    return base.with_orders(
                        [mirrored_id],
                        trace=[{"step": "payment_mirror_fallback"}],
                    )
                return self._api_failure(base, payment, "payment_resolution_failed")

            order_ref = payment.get("order") if isinstance(payment.get("order"), dict) else {}
            order_type = str(order_ref.get("type") or "").strip().lower()
            order_id = _numeric_id(order_ref.get("id"))
            if order_id and order_type in {"mercadolibre", "marketplace"}:
                return base.with_orders(
                    [order_id],
                    trace=[{"step": "typed_payment_order", "order_type": order_type}],
                )

            # Some legacy marketplace responses expose order_id at the root. It is
            # accepted only when the response also identifies the marketplace type.
            root_order_id = _numeric_id(payment.get("order_id"))
            root_type = str(payment.get("order_type") or payment.get("type") or "").lower()
            if root_order_id and root_type in {"mercadolibre", "marketplace"}:
                return base.with_orders(
                    [root_order_id],
                    trace=[{"step": "typed_root_payment_order", "order_type": root_type}],
                )

            mirrored = payment_lookup(resource.resource_id) if payment_lookup else None
            mirrored_id = _numeric_id((mirrored or {}).get("codigo_pedido"))
            if mirrored_id:
                return base.with_orders(
                    [mirrored_id],
                    trace=[{"step": "payment_mirror_fallback"}],
                )
            return WebhookResolution(
                self.provider,
                "order_event",
                "unresolved_payment",
                resources=(resource,),
                error_type="payment_without_order_reference",
                message="Pagamento Mercado Livre sem order do tipo mercadolivre",
            )

        return WebhookResolution(
            self.provider,
            "invalid",
            "unsupported_resource",
            resources=(resource,),
            error_type="unsupported_provider_resource",
            message=f"Recurso Mercado Livre nao suportado: {resource.resource_type}",
        )

    @staticmethod
    def _api_failure(
        base: WebhookResolution,
        result: dict,
        fallback_error: str,
    ) -> WebhookResolution:
        return WebhookResolution(
            base.provider,
            base.classification,
            "provider_error",
            resources=base.resources,
            error_type=result.get("error_type") or fallback_error,
            message=result.get("error") or fallback_error,
            retryable=bool(result.get("retryable")),
            retry_after=result.get("retry_after"),
        )

    def fetch_order_snapshot(self, order_id: str, integration: dict) -> CanonicalOrderSnapshot | dict:
        requested_order_id = _numeric_id(order_id)
        if not requested_order_id:
            return {
                "error": "ID de pedido Mercado Livre invalido",
                "error_type": "invalid_provider_resource_id",
                "retryable": False,
            }
        order = meli_driver.get_order_detail(integration, [requested_order_id])
        if not order or order.get("error"):
            return order or {"error": "Pedido nao encontrado no Mercado Livre"}
        returned_order_id = _numeric_id(order.get("id"))
        if returned_order_id != requested_order_id:
            return {
                "error": "Mercado Livre retornou pedido diferente do solicitado",
                "error_type": "provider_identity_mismatch",
                "retryable": False,
            }
        shipment, sla = {}, {}
        shipment_id = _numeric_id((order.get("shipping") or {}).get("id"))
        if shipment_id:
            shipment_result = meli_driver.get_shipment(integration, shipment_id)
            if not shipment_result.get("error"):
                shipment = shipment_result
                sla_result = meli_driver.get_shipment_sla(integration, shipment_id)
                if not sla_result.get("error"):
                    sla = sla_result
        payments = order.get("payments") if isinstance(order.get("payments"), list) else []
        payment_status = next(
            (str(row.get("status")) for row in payments if isinstance(row, dict) and row.get("status")),
            None,
        )
        return CanonicalOrderSnapshot(
            provider=self.provider,
            order_id=requested_order_id,
            order_status=_text(order.get("status")),
            payment_status=payment_status,
            shipping_status=_text(shipment.get("status")),
            customer=order.get("buyer") or {},
            items=tuple(order.get("order_items") or []),
            logistics={"shipment": shipment, "sla": sla},
            timestamps={
                "created_at": order.get("date_created"),
                "updated_at": order.get("last_updated"),
            },
            total=order.get("total_amount"),
            currency=order.get("currency_id") or "BRL",
            raw={
                "external_id": requested_order_id,
                "order": order,
                "shipment": shipment,
                "sla": sla,
            },
        )

    @staticmethod
    def normalize_lifecycle(snapshot: CanonicalOrderSnapshot | dict, event: dict):
        detail = snapshot.raw if isinstance(snapshot, CanonicalOrderSnapshot) else snapshot
        return resolve_mercadolivre(detail, event)


class ShopeeAdapter:
    provider = "shopee"
    ORDER_CODE = 3
    CHAT_CODE = 10

    def parse_webhook(self, payload: dict) -> WebhookResolution:
        payload = payload or {}
        body = _body(payload)
        try:
            code = int(payload.get("code", body.get("code")))
        except (TypeError, ValueError):
            code = None
        shop_id = _numeric_id(payload.get("shop_id") or body.get("shop_id"))
        event_id = _text(payload.get("msg_id") or body.get("event_id"))
        occurred_at = _text(payload.get("timestamp") or body.get("update_time"))

        if code == self.CHAT_CODE:
            resource_id = _text(
                ((body.get("content") or {}).get("message_id")
                 if isinstance(body.get("content"), dict) else None)
                or event_id
            ) or "chat"
            ref = MarketplaceResourceRef(
                self.provider, "chat", resource_id, "/sellerchat/push",
                account_id=shop_id, provider_event_id=event_id,
                occurred_at=occurred_at, topic=str(code),
            )
            return WebhookResolution(
                self.provider, "chat", "parsed", resources=(ref,)
            )

        if code != self.ORDER_CODE:
            classification = "verification" if code == 0 else "unsupported"
            return WebhookResolution(
                self.provider,
                classification,
                "unsupported_event",
                message=f"Push Shopee nao relacionado a pedido: code={code}",
            )

        order_sn = _text(body.get("ordersn") or body.get("order_sn"))
        if not order_sn or not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", order_sn):
            return WebhookResolution(
                self.provider,
                "invalid",
                "invalid_order_reference",
                error_type="invalid_provider_resource_id",
                message="Push Shopee sem ordersn valido",
            )
        if not shop_id:
            return WebhookResolution(
                self.provider,
                "invalid",
                "missing_shop_id",
                error_type="missing_marketplace_account_id",
                message="Push Shopee sem shop_id valido",
            )
        reference = MarketplaceResourceRef(
            self.provider,
            "order",
            order_sn,
            f"/api/v2/order/get_order_detail/{order_sn}",
            account_id=shop_id,
            provider_event_id=event_id,
            occurred_at=occurred_at,
            topic=str(code),
        )
        return WebhookResolution(
            self.provider,
            "order_event",
            "parsed",
            resources=(reference,),
            resolved_order_ids=(order_sn,),
            trace=({"step": "order_status_push"},),
        )

    def resolve_order_ids(
        self,
        resource: MarketplaceResourceRef,
        integration: dict,
        **_kwargs,
    ) -> WebhookResolution:
        if resource.resource_type != "order":
            return WebhookResolution(
                self.provider, "invalid", "unsupported_resource",
                resources=(resource,), error_type="unsupported_provider_resource",
            )
        return WebhookResolution(
            self.provider,
            "order_event",
            "resolved",
            resources=(resource,),
            resolved_order_ids=(resource.resource_id,),
        )

    def fetch_order_snapshot(self, order_id: str, integration: dict) -> CanonicalOrderSnapshot | dict:
        detail = shopee_driver.get_order_detail(integration, [order_id])
        if detail.get("error"):
            return detail
        if str(detail.get("external_id") or "") != str(order_id):
            return {
                "error": "Shopee retornou pedido diferente do solicitado",
                "error_type": "provider_identity_mismatch",
                "retryable": False,
            }
        return CanonicalOrderSnapshot(
            provider=self.provider,
            order_id=str(order_id),
            order_status=_text(detail.get("order_status")),
            return_status=_text(detail.get("return_status") or detail.get("refund_status")),
            customer={
                "id": detail.get("buyer_user_id"),
                "username": detail.get("buyer_username"),
                "recipient_address": detail.get("recipient_address"),
            },
            items=tuple(detail.get("item_list") or []),
            logistics={
                "shipping_carrier": detail.get("shipping_carrier"),
                "fulfillment_flag": detail.get("fulfillment_flag"),
                "package_list": detail.get("package_list") or [],
            },
            timestamps={
                "created_at": detail.get("create_time"),
                "updated_at": detail.get("update_time"),
                "paid_at": detail.get("pay_time"),
                "shipped_at": detail.get("ship_time"),
            },
            total=detail.get("total"),
            currency=detail.get("currency") or "BRL",
            raw=detail,
        )

    @staticmethod
    def normalize_lifecycle(snapshot: CanonicalOrderSnapshot | dict, event: dict):
        detail = snapshot.raw if isinstance(snapshot, CanonicalOrderSnapshot) else snapshot
        return resolve_shopee(detail, event)


mercadolivre_adapter = MercadoLivreAdapter()
shopee_adapter = ShopeeAdapter()
