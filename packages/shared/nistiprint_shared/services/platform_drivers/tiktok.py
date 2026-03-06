import requests
import time
import hashlib
import hmac
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("TikTokDriver")

def _generate_signature(app_key: str, app_secret: str, path: str, params: Dict) -> str:
    """
    Generates signature for TikTok Shop API requests
    """
    # Sort parameters by key
    sorted_params = sorted(params.items())
    
    # Create query string
    query_string = '&'.join([f'{k}={v}' for k, v in sorted_params])
    
    # Create string to sign
    string_to_sign = f"/{path}\n{app_key}\n{int(time.time())}\n{query_string}"
    
    # Generate signature using HMAC-SHA256
    signature = hmac.new(
        app_secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature


def get_order_detail(integration: Dict, order_ids: List[str]) -> Dict:
    """
    Fetches order details from TikTok Shop API for a given integration instance.
    """
    # Extract credentials
    config = integration.get("config", {})
    credentials = integration.get("credentials", {})
    
    app_key = config.get("app_key") or credentials.get("app_key")
    app_secret = config.get("app_secret") or credentials.get("app_secret")
    access_token = credentials.get("access_token")
    shop_cipher = credentials.get("shop_cipher") or config.get("shop_id")

    if not app_key or not app_secret or not shop_cipher:
        raise ValueError("Credenciais para TikTok Shop incompletas (app_key, app_secret e shop_cipher são obrigatórios).")

    if not access_token:
        raise ValueError("Access token para TikTok Shop não encontrado.")

    # Prepare request
    host = "https://open-api.tiktokglobalshop.com"
    path = "api/orders/detail"
    url = f"{host}/{path}"

    if not order_ids:
        return {"error": "Nenhum ID de pedido fornecido."}
    
    # Prepare parameters
    params = {
        "app_key": app_key,
        "timestamp": int(time.time()),
        "access_token": access_token,
        "shop_cipher": shop_cipher,
        "order_id": order_ids[0]  # Using first order ID
    }

    # Generate signature
    signature = _generate_signature(app_key, app_secret, path, params)
    params["sign"] = signature

    headers = {
        "Content-Type": "application/json"
    }

    print(f"DEBUG: TikTok Shop API URL: {url}")
    print(f"DEBUG: TikTok Shop API Params: {params}")

    response = requests.get(url, headers=headers, params=params)

    # Log raw response for debugging
    print(f"DEBUG: TikTok Shop API Raw Response Status: {response.status_code}")
    print(f"DEBUG: TikTok Shop API Raw Response Body: {response.text}")

    if response.status_code != 200:
        return {"error": f"Erro na API do TikTok Shop: {response.status_code}", "details": response.text}

    data = response.json()
    return data


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    """
    Fetches list of orders from TikTok Shop API for a given integration instance.
    """
    # Extract credentials
    config = integration.get("config", {})
    credentials = integration.get("credentials", {})

    app_key = config.get("app_key") or credentials.get("app_key")
    app_secret = config.get("app_secret") or credentials.get("app_secret")
    access_token = credentials.get("access_token")
    shop_cipher = credentials.get("shop_cipher") or config.get("shop_id")

    if not app_key or not app_secret or not shop_cipher:
        raise ValueError("Credenciais para TikTok Shop incompletas (app_key, app_secret e shop_cipher são obrigatórios).")

    if not access_token:
        raise ValueError("Access token para TikTok Shop não encontrado.")

    # Prepare request
    host = "https://open-api.tiktokglobalshop.com"
    path = "api/orders/list"
    url = f"{host}/{path}"

    # Prepare parameters
    params = {
        "app_key": app_key,
        "timestamp": int(time.time()),
        "access_token": access_token,
        "shop_cipher": shop_cipher
    }

    # Apply filters if provided
    if filters:
        # Common TikTok Shop API order list filters
        create_time_from = filters.get("create_time_from")
        create_time_to = filters.get("create_time_to")
        update_time_from = filters.get("update_time_from")
        update_time_to = filters.get("update_time_to")
        order_status = filters.get("order_status")
        page_size = filters.get("page_size", 50)
        page_number = filters.get("page_number", 1)

        if create_time_from:
            params["create_time_from"] = create_time_from
        if create_time_to:
            params["create_time_to"] = create_time_to
        if update_time_from:
            params["update_time_from"] = update_time_from
        if update_time_to:
            params["update_time_to"] = update_time_to
        if order_status:
            params["order_status"] = order_status
        if page_size:
            params["page_size"] = min(page_size, 50)  # Max 50 per request for TikTok
        if page_number:
            params["page_number"] = page_number

    # Generate signature
    signature = _generate_signature(app_key, app_secret, path, params)
    params["sign"] = signature

    headers = {
        "Content-Type": "application/json"
    }

    print(f"DEBUG: TikTok Shop API Orders List URL: {url}")
    print(f"DEBUG: TikTok Shop API Orders List Params: {params}")

    response = requests.get(url, headers=headers, params=params)

    # Log raw response for debugging
    print(f"DEBUG: TikTok Shop API Orders List Raw Response Status: {response.status_code}")
    print(f"DEBUG: TikTok Shop API Orders List Raw Response Body: {response.text}")

    if response.status_code != 200:
        return [{"error": f"Erro na API do TikTok Shop: {response.status_code}", "details": response.text}]

    data = response.json()

    # Normalizar os dados para o DTO padrão
    normalized_orders = []

    # TikTok Shop returns orders in a "data" object inside the response
    orders = data.get("data", {}).get("order_list", []) if "data" in data else []

    for order in orders:
        normalized_order = {
            "external_id": str(order.get("order_id", "")),
            "platform": "tiktok",
            "status_original": order.get("status", ""),
            "date_created": order.get("create_time", ""),
            "total": float(order.get("total_amount", 0)),
            "currency": order.get("currency", "USD"),
            "customer": {
                "name": order.get("customer_name", ""),
                "id": str(order.get("customer_id", ""))
            },
            "raw": order
        }
        normalized_orders.append(normalized_order)

    return normalized_orders

