import hmac
import hashlib
import time
import requests
import logging
import os
import re
from typing import List, Dict, Optional
from nistiprint_shared.utils.date_utils import unix_to_app_iso
from nistiprint_shared.services.marketplace_http import request_json

logger = logging.getLogger("shopee_driver")

SHOPEE_TRANSIENT_CODES = {
    "error_network", "internal_server_error", "error_server",
    "system_busy", "error_rate_limit",
}
SHOPEE_AUTH_CODES = {
    "error_auth", "error_sign", "invalid_access_token",
    "invalid_acceess_token", "error_api_permission", "user_is_unauthorized",
}


def _sanitize_order_sn(value: str) -> str:
    order_sn = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", order_sn):
        raise ValueError(f"order_sn Shopee invalido: {value!r}")
    return order_sn


def _shopee_api_error(data: dict, *, resource_type: str, resource_id: str | None = None) -> dict:
    code = str(data.get("error") or "")
    if code in SHOPEE_AUTH_CODES:
        error_type, retryable = "credential_action_required", False
    elif code in SHOPEE_TRANSIENT_CODES:
        error_type, retryable = "provider_transient_error", True
    else:
        error_type, retryable = "provider_parameter_error", False
    return {
        "error": data.get("message") or "Erro reportado pela Shopee",
        "code": code,
        "error_type": error_type,
        "retryable": retryable,
        "resource_type": resource_type,
        "resource_id": resource_id,
    }

def _ts_to_iso(ts: Optional[int]) -> Optional[str]:
    """Convert Unix timestamp to ISO 8601 string."""
    return unix_to_app_iso(ts)

def _carrier_from_packages(pkgs: Optional[List]) -> Optional[str]:
    """Extract shipping_carrier from package_list if available."""
    if not pkgs:
        return None
    for p in pkgs:
        if p.get("shipping_carrier"):
            return p["shipping_carrier"]
    return None

def _generate_sign(partner_id: int, partner_key: str, path: str, timestamp: int, access_token: Optional[str] = None, shop_id: Optional[int] = None) -> str:
    """Generates Shopee V2 signature."""
    if access_token and shop_id is not None:
        base_string = f"{partner_id}{path}{timestamp}{access_token}{shop_id}"
    else:
        base_string = f"{partner_id}{path}{timestamp}"
        
    sign = hmac.new(
        partner_key.encode('utf-8'),
        base_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return sign

def _resolve_credentials(integration: Dict) -> Dict:
    config = integration.get("config", {}) or {}
    credentials = integration.get("credentials", {}) or {}
    legacy_credentials = integration.get("_legacy_credentials", {}) or {}

    def find_value(*keys):
        for container in (config, credentials, legacy_credentials, integration):
            if not isinstance(container, dict):
                continue
            for key in keys:
                value = container.get(key)
                if value not in (None, ""):
                    return value
        return None

    account_identifiers = config.get("account_identifiers") or credentials.get("account_identifiers") or {}
    account_shop_id = account_identifiers.get("primary") if isinstance(account_identifiers, dict) else None

    return {
        "partner_id": find_value("partner_id") or os.getenv("SHOPEE_PARTNER_ID"),
        "partner_key": find_value("partner_key", "app_secret", "secret") or os.getenv("SHOPEE_PARTNER_KEY"),
        "shop_id": find_value("shop_id", "shopid", "shop_cipher") or account_shop_id,
        "access_token": find_value("access_token"),
    }

def test_connection(integration: Dict, path: Optional[str] = None) -> Dict:
    """
    Tests Shopee connectivity using the same credential sources as order ingest.
    """
    host = "https://partner.shopeemobile.com"
    path = path or "/api/v2/shop/get_profile"
    resolved = _resolve_credentials(integration)
    partner_id_raw = resolved.get("partner_id")
    partner_key = resolved.get("partner_key")
    shop_id_raw = resolved.get("shop_id")
    access_token = resolved.get("access_token")

    if not all([partner_id_raw, partner_key, shop_id_raw, access_token]):
        missing = []
        if not partner_id_raw:
            missing.append("partner_id")
        if not partner_key:
            missing.append("partner_key")
        if not shop_id_raw:
            missing.append("shop_id")
        if not access_token:
            missing.append("access_token")
        raise ValueError(
            "Configuracao da Shopee incompleta "
            f"({', '.join(missing)} ausentes). Verifique a instalacao e as variaveis "
            "SHOPEE_PARTNER_ID/SHOPEE_PARTNER_KEY."
        )

    partner_id = int(partner_id_raw)
    shop_id = int(shop_id_raw)
    timestamp = int(time.time())
    sign = _generate_sign(partner_id, partner_key, path, timestamp, access_token, shop_id)
    result = request_json(
        requests.get,
        f"{host}{path}",
        provider="Shopee",
        resource_type="connection",
        params={
            "partner_id": partner_id,
            "timestamp": timestamp,
            "sign": sign,
            "access_token": access_token,
            "shop_id": shop_id,
        },
    )
    if not result.ok:
        return {"success": False, "message": result.message, **result.to_legacy()}
    data = result.value or {}
    if data.get("error"):
        return {
            "success": False,
            "message": data.get("message") or "Erro reportado pela Shopee",
            **_shopee_api_error(data, resource_type="connection"),
        }

    return {"success": True, "message": "Conexao estabelecida com sucesso.", "details": data}

def get_order_detail(integration: Dict, order_sn_list: List[str]) -> Dict:
    """
    Fetches order details from Shopee V2 API for a given integration instance.
    """
    host = "https://partner.shopeemobile.com"
    
    resolved = _resolve_credentials(integration)
    partner_id_raw = resolved.get("partner_id")
    partner_key = resolved.get("partner_key")
    shop_id_raw = resolved.get("shop_id")
    access_token = resolved.get("access_token")

    if not all([partner_id_raw, partner_key, shop_id_raw, access_token]):
        raise ValueError("Configuração da Shopee incompleta (partner_id, partner_key, shop_id ou access_token ausentes). Verifique SHOPEE_PARTNER_ID e SHOPEE_PARTNER_KEY nas variáveis de ambiente.")

    partner_id = int(partner_id_raw)
    shop_id = int(shop_id_raw)
    
    # Prepare Request
    path = "/api/v2/order/get_order_detail"
    timestamp = int(time.time())
    sign = _generate_sign(partner_id, partner_key, path, timestamp, access_token, shop_id)
    
    url = f"{host}{path}"
    sanitized_order_sns = [_sanitize_order_sn(value) for value in order_sn_list]
    params = {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": sign,
        "access_token": access_token,
        "shop_id": shop_id,
        "order_sn_list": ",".join(sanitized_order_sns)
    }
    
    # Optional fields to get more info (like buyer details, items, etc)
    optional_fields = "buyer_user_id,buyer_username,recipient_address,item_list,create_time,update_time,pay_time,ship_time,total_amount,order_status,fulfillment_flag,package_list,shipping_carrier,message_to_seller,ship_by_date"
    params["response_optional_fields"] = optional_fields

    logger.info(
        "[shopee] fetching resource_type=order count=%s shop_id=%s",
        len(sanitized_order_sns), shop_id,
    )
    result = request_json(
        requests.get,
        url,
        provider="Shopee",
        resource_type="order",
        resource_id=sanitized_order_sns[0] if sanitized_order_sns else None,
        params=params,
    )
    if not result.ok:
        return result.to_legacy()
    data = result.value or {}
    if data.get("error"):
        return _shopee_api_error(
            data, resource_type="order",
            resource_id=sanitized_order_sns[0] if sanitized_order_sns else None,
        )
        
    # Normalizar para DTO
    raw_response = data.get("response", {})
    order_list = raw_response.get("order_list", [])
    
    if not order_list:
        return {
            "error": "Pedido nao encontrado na Shopee.",
            "error_type": "provider_resource_not_found",
            "retryable": False,
        }

    # Pegamos o primeiro pois a busca é por ID específico
    order = order_list[0]
    if str(order.get("order_sn") or "") != sanitized_order_sns[0]:
        return {
            "error": "Shopee retornou pedido diferente do solicitado",
            "error_type": "provider_identity_mismatch",
            "retryable": False,
        }

    normalized_order = _normalize_order(order, shop_id)

    logger.info("[shopee] order_detail fetched order_sn=%s status=%s shipping_carrier=%s fulfillment_flag=%s",
                order.get("order_sn"), order.get("order_status"),
                normalized_order.get("shipping_carrier"), order.get("fulfillment_flag"))

    return normalized_order


def _normalize_order(order: Dict, shop_id: int) -> Dict:
    """Converte um item de `order_list` da Shopee no DTO interno."""
    return {
        "external_id":        order.get("order_sn", ""),
        "platform":           "shopee",
        "shop_id":            shop_id,
        "order_status":       order.get("order_status"),
        "fulfillment_flag":   order.get("fulfillment_flag"),
        "shipping_carrier":   order.get("shipping_carrier")
                              or _carrier_from_packages(order.get("package_list")),
        "package_list":       order.get("package_list"),
        "item_list":          order.get("item_list"),
        "buyer_username":     order.get("buyer_username"),
        "buyer_user_id":      order.get("buyer_user_id"),
        "recipient_address":  order.get("recipient_address"),
        "pay_time":           _ts_to_iso(order.get("pay_time")),
        "create_time":        _ts_to_iso(order.get("create_time")),
        "update_time":        _ts_to_iso(order.get("update_time")),
        "ship_time":          _ts_to_iso(order.get("ship_time")),
        "ship_by_date":       _ts_to_iso(order.get("ship_by_date")),
        "return_status":      order.get("return_status"),
        "refund_status":      order.get("refund_status"),
        "total":              float(order.get("total_amount", 0)),
        "currency":           order.get("currency", "BRL"),
        "raw":                order,
    }


#: Teto da Shopee para `order_sn_list` em get_order_detail.
ORDER_DETAIL_BATCH_SIZE = 50


def get_order_details_batch(integration: Dict, order_sn_list: List[str]) -> Dict[str, Dict]:
    """Detalhe de varios pedidos, agrupando ate 50 por chamada.

    `get_order_detail` aceita lista na assinatura, mas tem semantica de pedido
    unico: le `order_list[0]` e confere a identidade contra o primeiro
    `order_sn` pedido. Passar 50 ali devolveria so o primeiro, em silencio — por
    isso esta funcao existe em vez de um parametro novo naquela.

    A confirmacao de identidade continua valendo, agora por chave: cada pedido
    devolvido e indexado pelo proprio `order_sn`, entao um pedido ausente na
    resposta vira erro explicito e nunca herda o detalhe de outro.

    Retorna `{order_sn: detalhe_ou_erro}` — o chamador trata cada pedido
    individualmente, como se tivesse buscado um a um.
    """
    resultado: Dict[str, Dict] = {}
    solicitados: List[str] = []
    for value in order_sn_list:
        if not value:
            continue
        try:
            solicitados.append(_sanitize_order_sn(value))
        except ValueError as exc:
            # Um identificador corrompido no banco nao pode derrubar o lote
            # inteiro: os outros 49 pedidos nao tem culpa.
            resultado[str(value)] = {
                "error": str(exc),
                "error_type": "invalid_provider_resource_id",
                "retryable": False,
            }
    if not solicitados:
        return resultado

    host = "https://partner.shopeemobile.com"
    path = "/api/v2/order/get_order_detail"
    optional_fields = (
        "buyer_user_id,buyer_username,recipient_address,item_list,create_time,"
        "update_time,pay_time,ship_time,total_amount,order_status,fulfillment_flag,"
        "package_list,shipping_carrier,message_to_seller,ship_by_date"
    )

    for inicio in range(0, len(solicitados), ORDER_DETAIL_BATCH_SIZE):
        lote = solicitados[inicio:inicio + ORDER_DETAIL_BATCH_SIZE]
        try:
            resolved = _resolve_credentials(integration)
            partner_id_raw = resolved.get("partner_id")
            partner_key = resolved.get("partner_key")
            shop_id_raw = resolved.get("shop_id")
            access_token = resolved.get("access_token")
            if not all([partner_id_raw, partner_key, shop_id_raw, access_token]):
                raise ValueError("Configuracao da Shopee incompleta")

            partner_id = int(partner_id_raw)
            shop_id = int(shop_id_raw)
            timestamp = int(time.time())
            sign = _generate_sign(
                partner_id, partner_key, path, timestamp, access_token, shop_id
            )

            logger.info(
                "[shopee] fetching resource_type=order count=%s shop_id=%s (lote)",
                len(lote), shop_id,
            )
            result = request_json(
                requests.get,
                f"{host}{path}",
                provider="Shopee",
                resource_type="order",
                resource_id=lote[0],
                params={
                    "partner_id": partner_id,
                    "timestamp": timestamp,
                    "sign": sign,
                    "access_token": access_token,
                    "shop_id": shop_id,
                    "order_sn_list": ",".join(lote),
                    "response_optional_fields": optional_fields,
                },
            )

            if not result.ok:
                falha = result.to_legacy()
            elif (result.value or {}).get("error"):
                falha = _shopee_api_error(
                    result.value or {}, resource_type="order", resource_id=lote[0],
                )
            else:
                falha = None
        except Exception as exc:
            falha = {"error": str(exc), "error_type": "batch_request_failed"}

        if falha is not None:
            # Falha de lote nao pode virar "pedido nao encontrado": sao coisas
            # diferentes e so uma delas justifica parar de tentar.
            for order_sn in lote:
                resultado[order_sn] = dict(falha)
            continue

        encontrados = {
            str(order.get("order_sn") or ""): order
            for order in ((result.value or {}).get("response", {}) or {}).get("order_list", [])
            or []
        }
        for order_sn in lote:
            order = encontrados.get(order_sn)
            if order is None:
                resultado[order_sn] = {
                    "error": "Pedido nao encontrado na Shopee.",
                    "error_type": "provider_resource_not_found",
                    "retryable": False,
                }
            else:
                resultado[order_sn] = _normalize_order(order, shop_id)

    return resultado

def get_return_detail(integration: Dict, return_sn: str) -> Dict:
    """Fetch a Shopee return/refund resource and expose its order identity."""
    host = "https://partner.shopeemobile.com"
    path = "/api/v2/returns/get_return_detail"
    resolved = _resolve_credentials(integration)
    if not all(resolved.values()):
        return {"error": "Configuracao da Shopee incompleta para consultar devolucao."}
    partner_id = int(resolved["partner_id"])
    shop_id = int(resolved["shop_id"])
    timestamp = int(time.time())
    sign = _generate_sign(
        partner_id, resolved["partner_key"], path, timestamp,
        resolved["access_token"], shop_id,
    )
    result = request_json(
        requests.get,
        f"{host}{path}",
        provider="Shopee",
        resource_type="return",
        resource_id=str(return_sn),
        params={
            "partner_id": partner_id,
            "timestamp": timestamp,
            "sign": sign,
            "access_token": resolved["access_token"],
            "shop_id": shop_id,
            "return_sn": str(return_sn),
        },
    )
    if not result.ok:
        return result.to_legacy()
    data = result.value or {}
    if data.get("error"):
        return _shopee_api_error(data, resource_type="return", resource_id=str(return_sn))
    payload = data.get("response") or {}
    if isinstance(payload.get("return"), dict):
        payload = payload["return"]
    return payload if isinstance(payload, dict) else {"error": "Devolucao Shopee invalida"}


def get_product_detail(integration: Dict, item_id_list: List[str]) -> Dict:
    """
    Placeholder for fetching product details from Shopee V2 API.
    """
    # Implementation would follow a similar pattern to get_order_detail
    # using /api/v2/product/get_item_base_info or similar
    return {"error": "Consulta de produtos Shopee ainda não implementada."}


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    """
    Fetches list of orders from Shopee V2 API for a given integration instance.
    """
    host = "https://partner.shopeemobile.com"

    # Extract Credentials
    config = integration.get("config", {})
    credentials = integration.get("credentials", {})

    partner_id_raw = config.get("partner_id") or credentials.get("partner_id") or os.getenv("SHOPEE_PARTNER_ID")
    partner_key = config.get("partner_key") or credentials.get("partner_key") or os.getenv("SHOPEE_PARTNER_KEY")
    shop_id_raw = config.get("shop_id") or credentials.get("shop_id")
    access_token = integration.get("access_token") or credentials.get("access_token")

    if not all([partner_id_raw, partner_key, shop_id_raw, access_token]):
        raise ValueError("Configuração da Shopee incompleta (partner_id, partner_key, shop_id ou access_token ausentes). Verifique SHOPEE_PARTNER_ID e SHOPEE_PARTNER_KEY nas variáveis de ambiente.")

    partner_id = int(partner_id_raw)
    shop_id = int(shop_id_raw)

    # Prepare Request
    path = "/api/v2/order/get_order_list"
    timestamp = int(time.time())
    sign = _generate_sign(partner_id, partner_key, path, timestamp, access_token, shop_id)

    url = f"{host}{path}"

    # Prepare filters
    params = {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": sign,
        "access_token": access_token,
        "shop_id": shop_id,
        "time_range_field": "create_time" # Default required field
    }

    # Apply filters if provided
    if filters:
        # Abstraction mapping: map generic keys to Shopee specific ones
        time_from = filters.get("time_from") or filters.get("create_time_from") or filters.get("start_date")
        time_to = filters.get("time_to") or filters.get("create_time_to") or filters.get("end_date")
        
        if time_from:
            params["time_from"] = int(time_from)
        if time_to:
            params["time_to"] = int(time_to)
            
        if filters.get("time_range_field"):
            params["time_range_field"] = filters.get("time_range_field")
            
        if filters.get("order_status"):
            params["order_status"] = filters.get("order_status")
            
        if filters.get("page_size"):
            params["page_size"] = int(filters.get("page_size"))
        else:
            params["page_size"] = 20 # Shopee default/required

        if filters.get("cursor"):
            params["cursor"] = filters.get("cursor")

    # Shopee V2 requires time_from and time_to if time_range_field is provided
    # If not provided in filters, we'll default to last 15 days
    if "time_from" not in params:
        params["time_from"] = int(time.time()) - (15 * 24 * 3600)
    if "time_to" not in params:
        params["time_to"] = int(time.time())

    # Add optional fields as requested to maintain consistency with detail view
    params["response_optional_fields"] = "order_status"

    logger.info("[shopee] fetching resource_type=orders_list shop_id=%s", shop_id)
    result = request_json(
        requests.get,
        url,
        provider="Shopee",
        resource_type="orders_list",
        params=params,
    )
    if not result.ok:
        return [result.to_legacy()]
    data = result.value or {}
    if data.get("error"):
        return [_shopee_api_error(data, resource_type="orders_list")]

    # Normalizar os dados para o DTO padrão
    normalized_orders = []
    raw_response = data.get("response", {})
    order_list = raw_response.get("order_list", [])

    for order in order_list:
        # Converter timestamp Unix para ISO 8601
        create_time_iso = ""
        if "create_time" in order:
            create_time_iso = unix_to_app_iso(order["create_time"]) or ""

        normalized_order = {
            "external_id": order.get("order_sn", ""),
            "platform": "shopee",
            "status_original": order.get("order_status", ""),
            "date_created": create_time_iso,
            "total": float(order.get("total_amount", 0)),
            "currency": order.get("currency", "BRL"),
            "customer": {
                "name": order.get("buyer_username", ""),
                "id": str(order.get("buyer_user_id", ""))
            },
            "raw": order
        }
        normalized_orders.append(normalized_order)

    return normalized_orders

