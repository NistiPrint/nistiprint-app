import requests
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("SheinDriver")

def get_order_detail(integration: Dict, order_ids: List[str]) -> Dict:
    """
    Fetches order details from Shein API for a given integration instance.
    """
    # Extract credentials
    config = integration.get("config", {})
    credentials = integration.get("credentials", {})
    
    api_key = config.get("api_key") or credentials.get("api_key")
    app_id = config.get("app_id") or credentials.get("app_id")
    access_token = credentials.get("access_token")

    if not api_key or not app_id:
        raise ValueError("Credenciais para Shein incompletas (api_key e app_id são obrigatórios).")

    headers = {
        "X-API-Key": api_key,
        "X-App-ID": app_id,
        "Content-Type": "application/json"
    }
    
    # Include access token if available
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    # Shein API endpoint for order details
    host = "https://openapi-sandbox.sheindx.com"  # Using sandbox URL as example
    if not order_ids:
        return {"error": "Nenhum ID de pedido fornecido."}
    
    # Using the first order ID as example (actual implementation may vary)
    order_id = order_ids[0]
    url = f"{host}/orders/{order_id}"

    print(f"DEBUG: Shein API URL: {url}")
    print(f"DEBUG: Shein API Headers: {headers}")

    response = requests.get(url, headers=headers)

    # Log raw response for debugging
    print(f"DEBUG: Shein API Raw Response Status: {response.status_code}")
    print(f"DEBUG: Shein API Raw Response Body: {response.text}")

    if response.status_code != 200:
        return {"error": f"Erro na API da Shein: {response.status_code}", "details": response.text}

    data = response.json()
    return data


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    """
    Fetches list of orders from Shein API for a given integration instance.
    """
    # Extract credentials
    config = integration.get("config", {})
    credentials = integration.get("credentials", {})

    api_key = config.get("api_key") or credentials.get("api_key")
    app_id = config.get("app_id") or credentials.get("app_id")
    access_token = credentials.get("access_token")

    if not api_key or not app_id:
        raise ValueError("Credenciais para Shein incompletas (api_key e app_id são obrigatórios).")

    headers = {
        "X-API-Key": api_key,
        "X-App-ID": app_id,
        "Content-Type": "application/json"
    }

    # Include access token if available
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    # Prepare URL and parameters
    host = "https://openapi-sandbox.sheinx.com"  # Using sandbox URL as example
    url = f"{host}/orders/list"

    # Prepare query parameters
    params = {}

    # Apply filters if provided
    if filters:
        # Common Shein API order list filters
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")
        order_status = filters.get("order_status")
        page_size = filters.get("page_size", 50)
        page_num = filters.get("page_num", 1)

        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if order_status:
            params["order_status"] = order_status
        if page_size:
            params["page_size"] = min(page_size, 100)  # Max 100 per request
        if page_num:
            params["page_num"] = page_num

    print(f"DEBUG: Shein API Orders List URL: {url}")
    print(f"DEBUG: Shein API Orders List Params: {params}")
    print(f"DEBUG: Shein API Headers: {headers}")

    response = requests.get(url, headers=headers, params=params)

    # Log raw response for debugging
    print(f"DEBUG: Shein API Orders List Raw Response Status: {response.status_code}")
    print(f"DEBUG: Shein API Orders List Raw Response Body: {response.text}")

    if response.status_code != 200:
        return [{"error": f"Erro na API da Shein: {response.status_code}", "details": response.text}]

    data = response.json()

    # Normalizar os dados para o DTO padrão
    normalized_orders = []

    # Shein returns orders in a "data" array inside the response (structure may vary)
    orders = data.get("data", [])

    for order in orders:
        normalized_order = {
            "external_id": str(order.get("order_id", "")),
            "platform": "shein",
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

