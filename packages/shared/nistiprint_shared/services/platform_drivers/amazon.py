import requests
import json
import time
import hashlib
import hmac
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("AmazonDriver")

def _sign_request(key: str, msg: str) -> str:
    """Helper function to sign requests using HMAC-SHA256"""
    return hmac.new(key.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).digest()


def _get_amazon_headers(access_token: str, region: str = "us-east-1") -> Dict:
    """Helper function to create headers for Amazon SP-API requests"""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "host": f"sellingpartnerapi-{region}.amazon.com"
    }


def get_order_detail(integration: Dict, order_ids: List[str]) -> Dict:
    """
    Fetches order details from Amazon SP-API for a given integration instance.
    """
    # Extract credentials and config
    config = integration.get("config", {})
    credentials = integration.get("credentials", {})
    
    access_token = credentials.get("access_token")
    refresh_token = credentials.get("refresh_token")
    client_id = config.get("client_id") or credentials.get("client_id")
    client_secret = config.get("client_secret") or credentials.get("client_secret")
    aws_access_key = config.get("aws_access_key") or credentials.get("aws_access_key")
    aws_secret_key = config.get("aws_secret_key") or credentials.get("aws_secret_key")
    role_arn = config.get("role_arn") or credentials.get("role_arn")
    region = config.get("region", "us-east-1")

    if not access_token:
        raise ValueError("Access token para Amazon não encontrado.")

    headers = _get_amazon_headers(access_token, region)

    # Amazon SP-API expects order IDs in the URL path
    if not order_ids:
        return {"error": "Nenhum ID de pedido fornecido."}
    
    # Using the first order ID as example (Amazon SP-API typically handles single order requests)
    order_id = order_ids[0]
    host = f"https://sellingpartnerapi-{region}.amazon.com"
    url = f"{host}/orders/v0/orders/{order_id}"

    print(f"DEBUG: Amazon SP-API URL: {url}")

    response = requests.get(url, headers=headers)

    # Log raw response for debugging
    print(f"DEBUG: Amazon SP-API Raw Response Status: {response.status_code}")
    print(f"DEBUG: Amazon SP-API Raw Response Body: {response.text}")

    if response.status_code != 200:
        return {"error": f"Erro na API da Amazon: {response.status_code}", "details": response.text}

    data = response.json()
    return data


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    """
    Fetches list of orders from Amazon SP-API for a given integration instance.
    """
    # Extract credentials and config
    config = integration.get("config", {})
    credentials = integration.get("credentials", {})

    access_token = credentials.get("access_token")
    refresh_token = credentials.get("refresh_token")
    client_id = config.get("client_id") or credentials.get("client_id")
    client_secret = config.get("client_secret") or credentials.get("client_secret")
    aws_access_key = config.get("aws_access_key") or credentials.get("aws_access_key")
    aws_secret_key = config.get("aws_secret_key") or credentials.get("aws_secret_key")
    role_arn = config.get("role_arn") or credentials.get("role_arn")
    region = config.get("region", "us-east-1")

    if not access_token:
        raise ValueError("Access token para Amazon não encontrado.")

    headers = _get_amazon_headers(access_token, region)

    # Prepare URL and parameters
    host = f"https://sellingpartnerapi-{region}.amazon.com"
    url = f"{host}/orders/v0/orders"

    # Prepare query parameters
    params = {}

    # Apply filters if provided
    if filters:
        # Common Amazon SP-API order list filters
        created_after = filters.get("created_after")
        created_before = filters.get("created_before")
        last_updated_after = filters.get("last_updated_after")
        last_updated_before = filters.get("last_updated_before")
        order_statuses = filters.get("order_statuses")  # List of statuses
        marketplace_ids = filters.get("marketplace_ids")  # List of marketplace IDs
        max_results_per_page = filters.get("max_results_per_page", 100)

        if created_after:
            params["CreatedAfter"] = created_after
        if created_before:
            params["CreatedBefore"] = created_before
        if last_updated_after:
            params["LastUpdatedAfter"] = last_updated_after
        if last_updated_before:
            params["LastUpdatedBefore"] = last_updated_before
        if order_statuses and isinstance(order_statuses, list):
            params["OrderStatuses"] = ",".join(order_statuses)
        if marketplace_ids and isinstance(marketplace_ids, list):
            params["MarketplaceIds"] = ",".join(marketplace_ids)
        if max_results_per_page:
            params["MaxResultsPerPage"] = min(max_results_per_page, 100)  # Max 100 per request

    print(f"DEBUG: Amazon SP-API Orders List URL: {url}")
    print(f"DEBUG: Amazon SP-API Orders List Params: {params}")

    response = requests.get(url, headers=headers, params=params)

    # Log raw response for debugging
    print(f"DEBUG: Amazon SP-API Orders List Raw Response Status: {response.status_code}")
    print(f"DEBUG: Amazon SP-API Orders List Raw Response Body: {response.text}")

    if response.status_code != 200:
        return [{"error": f"Erro na API da Amazon: {response.status_code}", "details": response.text}]

    data = response.json()

    # Normalizar os dados para o DTO padrão
    normalized_orders = []

    # Amazon returns orders in an "Orders" array inside the response
    orders = data.get("payload", {}).get("Orders", []) if "payload" in data else data.get("Orders", [])

    for order in orders:
        normalized_order = {
            "external_id": order.get("AmazonOrderId", ""),
            "platform": "amazon",
            "status_original": order.get("OrderStatus", ""),
            "date_created": order.get("PurchaseDate", ""),
            "total": float(order.get("OrderTotal", {}).get("Amount", 0)),
            "currency": order.get("OrderTotal", {}).get("CurrencyCode", "USD"),
            "customer": {
                "name": order.get("BuyerEmail", ""),  # Amazon PII protege o nome, usar email como alternativa
                "id": order.get("BuyerName", "")
            },
            "raw": order
        }
        normalized_orders.append(normalized_order)

    return normalized_orders

