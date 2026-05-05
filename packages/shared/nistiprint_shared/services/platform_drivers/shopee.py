import hmac
import hashlib
import time
import requests
import logging
import os
from typing import List, Dict, Optional
from nistiprint_shared.utils.date_utils import unix_to_app_iso

logger = logging.getLogger("shopee_driver")

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

def get_order_detail(integration: Dict, order_sn_list: List[str]) -> Dict:
    """
    Fetches order details from Shopee V2 API for a given integration instance.
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
    path = "/api/v2/order/get_order_detail"
    timestamp = int(time.time())
    sign = _generate_sign(partner_id, partner_key, path, timestamp, access_token, shop_id)
    
    url = f"{host}{path}"
    params = {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": sign,
        "access_token": access_token,
        "shop_id": shop_id,
        "order_sn_list": ",".join(order_sn_list)
    }
    
    # Optional fields to get more info (like buyer details, items, etc)
    optional_fields = "buyer_user_id,buyer_username,recipient_address,item_list,pay_time,total_amount,order_status,fulfillment_flag,package_list,shipping_carrier,message_to_seller"
    params["response_optional_fields"] = optional_fields

    logger.debug("Shopee API URL: %s", url)
    logger.debug("Shopee API Params: %s", params)

    response = requests.get(url, params=params)

    logger.debug("Shopee API Raw Response Status: %s", response.status_code)
    logger.debug("Shopee API Raw Response Body: %s", response.text)
    
    if response.status_code != 200:
        return {"error": f"Erro na API da Shopee: {response.status_code}", "details": response.text}
    
    data = response.json()
    if data.get("error"):
        return {"error": f"Erro reportado pela Shopee: {data.get('message')}", "code": data.get('error')}
        
    # Normalizar para DTO
    raw_response = data.get("response", {})
    order_list = raw_response.get("order_list", [])
    
    if not order_list:
        return {"error": "Pedido não encontrado na Shopee."}

    # Pegamos o primeiro pois a busca é por ID específico
    order = order_list[0]

    normalized_order = {
        "external_id":        order.get("order_sn", ""),
        "platform":           "shopee",
        "shop_id":            int(integration['config'].get('shop_id') or 0) or None,
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
        "total":              float(order.get("total_amount", 0)),
        "currency":           order.get("currency", "BRL"),
        "raw":                order,
    }

    logger.info("[shopee] order_detail fetched order_sn=%s status=%s shipping_carrier=%s fulfillment_flag=%s",
                order.get("order_sn"), order.get("order_status"),
                normalized_order.get("shipping_carrier"), order.get("fulfillment_flag"))

    return normalized_order

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

    logger.debug("Shopee API Orders List URL: %s", url)
    logger.debug("Shopee API Orders List Params: %s", params)

    response = requests.get(url, params=params)

    logger.debug("Shopee API Orders List Raw Response Status: %s", response.status_code)
    logger.debug("Shopee API Orders List Raw Response Body: %s", response.text)

    if response.status_code != 200:
        return [{"error": f"Erro na API da Shopee: {response.status_code}", "details": response.text}]

    data = response.json()
    if data.get("error"):
        return [{"error": f"Erro reportado pela Shopee: {data.get('message')}", "code": data.get('error')}]

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

