import requests
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("MercadoLivreDriver")

def get_order_detail(integration: Dict, order_ids: List[str]) -> Dict:
    """
    Fetches order details from Mercado Livre API for a given integration instance.
    """
    # Base URL for Mercado Livre API
    host = "https://api.mercadolibre.com"

    # Extract credentials
    credentials = integration.get("credentials", {})
    access_token = credentials.get("access_token")

    if not access_token:
        raise ValueError("Access token para Mercado Livre não encontrado.")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Since Mercado Livre API typically accepts one order ID at a time,
    # we'll fetch details for the first order in the list
    if not order_ids:
        return {"error": "Nenhum ID de pedido fornecido."}
    
    order_id = order_ids[0]  # Using first order ID as Mercado Livre typically uses single order queries
    url = f"{host}/orders/{order_id}"

    print(f"DEBUG: Mercado Livre API URL: {url}")

    response = requests.get(url, headers=headers)

    # Log raw response for debugging
    print(f"DEBUG: Mercado Livre API Raw Response Status: {response.status_code}")
    print(f"DEBUG: Mercado Livre API Raw Response Body: {response.text}")

    if response.status_code != 200:
        return {"error": f"Erro na API do Mercado Livre: {response.status_code}", "details": response.text}

    data = response.json()
    return data


def get_shipment(integration: Dict, shipment_id: str) -> Dict:
    """
    Fetches shipment details from Mercado Livre API.
    """
    host = "https://api.mercadolibre.com"
    credentials = integration.get("credentials", {})
    access_token = credentials.get("access_token")

    if not access_token:
        raise ValueError("Access token para Mercado Livre não encontrado.")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    url = f"{host}/shipments/{shipment_id}"
    logger.info(f"[ML Driver] Fetching shipment: {url}")
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        logger.error(f"[ML Driver] Error fetching shipment {shipment_id}: {response.status_code} - {response.text}")
        return {"error": f"Erro na API do Mercado Livre (shipments): {response.status_code}", "details": response.text}

    return response.json()


def get_shipment_sla(integration: Dict, shipment_id: str) -> Dict:
    """
    Fetches shipment SLA (Service Level Agreement) details from Mercado Livre API.
    Used to get the expected_date (shipping limit).
    """
    host = "https://api.mercadolibre.com"
    credentials = integration.get("credentials", {})
    access_token = credentials.get("access_token")

    if not access_token:
        raise ValueError("Access token para Mercado Livre não encontrado.")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    url = f"{host}/shipments/{shipment_id}/sla"
    logger.info(f"[ML Driver] Fetching shipment SLA: {url}")
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        logger.error(f"[ML Driver] Error fetching shipment SLA {shipment_id}: {response.status_code} - {response.text}")
        return {"error": f"Erro na API do Mercado Livre (shipments/sla): {response.status_code}", "details": response.text}

    return response.json()


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    """
    Fetches list of orders from Mercado Livre API for a given integration instance.
    """
    # Base URL for Mercado Livre API
    host = "https://api.mercadolibre.com"

    # Extract credentials
    credentials = integration.get("credentials", {})
    access_token = credentials.get("access_token")

    if not access_token:
        raise ValueError("Access token para Mercado Livre não encontrado.")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Prepare URL and parameters
    url = f"{host}/orders/search"

    params = {
        "sort": "date_desc",  # Sort by date descending by default
        "limit": 50  # Default limit
    }

    # Apply filters if provided
    if filters:
        # Common Mercado Livre order list filters
        date_created_from = filters.get("date_created_from")
        date_created_to = filters.get("date_created_to")
        last_updated_after = filters.get("last_updated_after")
        last_updated_before = filters.get("last_updated_before")
        order_status = filters.get("order_status")
        seller = filters.get("seller")  # seller nickname
        limit = filters.get("limit", 50)
        offset = filters.get("offset", 0)

        if date_created_from:
            params["date_created_from"] = date_created_from
        if date_created_to:
            params["date_created_to"] = date_created_to
        if last_updated_after:
            params["last_updated_after"] = last_updated_after
        if last_updated_before:
            params["last_updated_before"] = last_updated_before
        if order_status:
            params["order_status"] = order_status
        if seller:
            params["seller"] = seller
        if limit:
            params["limit"] = min(limit, 100)  # Max 100 per request
        if offset:
            params["offset"] = offset

    print(f"DEBUG: Mercado Livre API Orders List URL: {url}")
    print(f"DEBUG: Mercado Livre API Orders List Params: {params}")

    response = requests.get(url, headers=headers, params=params)

    # Log raw response for debugging
    print(f"DEBUG: Mercado Livre API Orders List Raw Response Status: {response.status_code}")
    print(f"DEBUG: Mercado Livre API Orders List Raw Response Body: {response.text}")

    if response.status_code != 200:
        return [{"error": f"Erro na API do Mercado Livre: {response.status_code}", "details": response.text}]

    data = response.json()

    # Normalizar os dados para o DTO padrão
    normalized_orders = []
    order_list = data.get("results", [])

    for order in order_list:
        # Obter nome do cliente
        buyer_name = ""
        buyer = order.get("buyer", {})
        if "nickname" in buyer:
            buyer_name = buyer["nickname"]
        elif "first_name" in buyer and "last_name" in buyer:
            buyer_name = f"{buyer['first_name']} {buyer['last_name']}"

        normalized_order = {
            "external_id": str(order.get("id", "")),
            "platform": "mercadolivre",
            "status_original": order.get("status", ""),
            "date_created": order.get("date_created", ""),
            "total": float(order.get("total_amount", 0)),
            "currency": order.get("currency_id", "BRL"),
            "customer": {
                "name": buyer_name,
                "id": str(buyer.get("id", ""))
            },
            "raw": order
        }
        normalized_orders.append(normalized_order)

    return normalized_orders

