import hmac
import hashlib
import time
import requests
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("ShopeeDriver")

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
    
    partner_id_raw = config.get("partner_id") or credentials.get("partner_id")
    partner_key = config.get("partner_key") or credentials.get("partner_key")
    shop_id_raw = config.get("shop_id") or credentials.get("shop_id")
    access_token = integration.get("access_token") or credentials.get("access_token")

    if not all([partner_id_raw, partner_key, shop_id_raw, access_token]):
        raise ValueError("Configuração da Shopee incompleta (partner_id, partner_key, shop_id ou access_token ausentes).")

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
    optional_fields = "buyer_user_id,buyer_username,recipient_address,item_list,pay_time,total_amount,order_status,fulfillment_flag,package_list,shipping_carrier"
    params["response_optional_fields"] = optional_fields
    
    print(f"DEBUG: Shopee API URL: {url}")
    print(f"DEBUG: Shopee API Params: {params}")
    
    response = requests.get(url, params=params)
    
    # Log raw response for debugging as requested
    print(f"DEBUG: Shopee API Raw Response Status: {response.status_code}")
    print(f"DEBUG: Shopee API Raw Response Body: {response.text}")
    
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
    
    # Converter timestamp
    create_time_iso = ""
    if "create_time" in order:
        import datetime
        create_time_iso = datetime.datetime.fromtimestamp(order["create_time"]).isoformat() + "Z"

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
        "raw": order # Importante para debug!
    }
        
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

    partner_id_raw = config.get("partner_id") or credentials.get("partner_id")
    partner_key = config.get("partner_key") or credentials.get("partner_key")
    shop_id_raw = config.get("shop_id") or credentials.get("shop_id")
    access_token = integration.get("access_token") or credentials.get("access_token")

    if not all([partner_id_raw, partner_key, shop_id_raw, access_token]):
        raise ValueError("Configuração da Shopee incompleta (partner_id, partner_key, shop_id ou access_token ausentes).")

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

    print(f"DEBUG: Shopee API Orders List URL: {url}")
    print(f"DEBUG: Shopee API Orders List Params: {params}")

    response = requests.get(url, params=params)

    # Log raw response for debugging as requested
    print(f"DEBUG: Shopee API Orders List Raw Response Status: {response.status_code}")
    print(f"DEBUG: Shopee API Orders List Raw Response Body: {response.text}")

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
            import datetime
            create_time_iso = datetime.datetime.fromtimestamp(order["create_time"]).isoformat() + "Z"

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

