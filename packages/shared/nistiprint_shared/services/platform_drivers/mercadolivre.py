import requests
import logging
from typing import List, Dict, Optional

from nistiprint_shared.services.marketplace_http import request_json

logger = logging.getLogger("MercadoLivreDriver")


ML_API_HOST = "https://api.mercadolibre.com"


def _sanitize_resource_id(value: str | int | None, *, resource_name: str) -> str:
    raw = str(value or "").strip().strip("/")
    if not raw:
        raise ValueError(f"{resource_name} id ausente")
    sanitized = raw.split("/", 1)[0].strip()
    if (
        not sanitized
        or sanitized.lower() in {"orders", "shipments", "payments", "collections", "packs"}
        or not sanitized.isdigit()
    ):
        raise ValueError(f"{resource_name} id invalido: {value!r}")
    return sanitized


def _ml_url(path: str) -> str:
    normalized = "/" + str(path or "").lstrip("/")
    return f"{ML_API_HOST}{normalized}"


def _resolve_access_token(integration: Dict) -> Optional[str]:
    credentials = integration.get("credentials", {}) or {}
    legacy_credentials = integration.get("_legacy_credentials", {}) or {}
    return (
        integration.get("access_token")
        or credentials.get("access_token")
        or legacy_credentials.get("access_token")
    )


def _auth_headers(integration: Dict) -> Dict:
    access_token = _resolve_access_token(integration)
    if not access_token:
        raise ValueError("Access token para Mercado Livre nao encontrado.")

    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


def test_connection(integration: Dict, path: Optional[str] = None) -> Dict:
    """
    Tests Mercado Livre connectivity using the same token source as the driver.
    """
    result = request_json(
        requests.get,
        _ml_url(path or "/users/me"),
        provider="Mercado Livre",
        resource_type="connection",
        headers=_auth_headers(integration),
    )
    if not result.ok:
        return {
            "success": False,
            "message": result.message,
            **result.to_legacy(),
        }
    return {
        "success": True,
        "message": "Conexao estabelecida com sucesso.",
        "details": result.value,
    }


def get_order_detail(integration: Dict, order_ids: List[str]) -> Dict:
    """
    Fetches order details from Mercado Livre API for a given integration instance.
    """
    headers = _auth_headers(integration)

    # Since Mercado Livre API typically accepts one order ID at a time,
    # we'll fetch details for the first order in the list
    if not order_ids:
        return {"error": "Nenhum ID de pedido fornecido."}
    
    order_id = order_ids[0]  # Using first order ID as Mercado Livre typically uses single order queries
    order_id = _sanitize_resource_id(order_id, resource_name="order")
    url = _ml_url(f"/orders/{order_id}")

    logger.info("[meli] fetching resource_type=order resource_id=%s", order_id)
    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="order",
        resource_id=order_id,
        success_statuses=(200, 206),
        headers=headers,
    ).to_legacy()


def get_payment(integration: Dict, payment_id: str) -> Dict:
    """
    Fetches payment details from Mercado Livre/Mercado Pago API.
    """
    headers = _auth_headers(integration)
    payment_id = _sanitize_resource_id(payment_id, resource_name="payment")

    url = _ml_url(f"/payments/{payment_id}")
    logger.info("[ML Driver] Fetching payment: %s", url)

    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="payment",
        resource_id=payment_id,
        headers=headers,
    ).to_legacy()


def get_collection(integration: Dict, collection_id: str) -> Dict:
    """Fetches a payment notification using the resource sent by Mercado Livre."""
    headers = _auth_headers(integration)
    collection_id = _sanitize_resource_id(collection_id, resource_name="collection")
    url = _ml_url(f"/collections/{collection_id}")
    logger.info("[ML Driver] Fetching collection: %s", url)
    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="collection",
        resource_id=collection_id,
        headers=headers,
    ).to_legacy()


def get_shipment(integration: Dict, shipment_id: str) -> Dict:
    """
    Fetches shipment details from Mercado Livre API.
    """
    headers = {**_auth_headers(integration), "x-format-new": "true"}
    shipment_id = _sanitize_resource_id(shipment_id, resource_name="shipment")

    url = _ml_url(f"/shipments/{shipment_id}")
    logger.info(f"[ML Driver] Fetching shipment: {url}")
    
    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="shipment",
        resource_id=shipment_id,
        headers=headers,
    ).to_legacy()


def get_shipment_sla(integration: Dict, shipment_id: str) -> Dict:
    """
    Fetches shipment SLA (Service Level Agreement) details from Mercado Livre API.
    Used to get the expected_date (shipping limit).
    """
    headers = _auth_headers(integration)
    shipment_id = _sanitize_resource_id(shipment_id, resource_name="shipment")

    url = _ml_url(f"/shipments/{shipment_id}/sla")
    logger.info(f"[ML Driver] Fetching shipment SLA: {url}")
    
    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="shipment",
        resource_id=shipment_id,
        headers=headers,
    ).to_legacy()


def get_pack(integration: Dict, pack_id: str) -> Dict:
    """Fetch a cart pack so one shipment can resolve all related orders."""
    headers = _auth_headers(integration)
    pack_id = _sanitize_resource_id(pack_id, resource_name="pack")
    url = _ml_url(f"/packs/{pack_id}")
    logger.info("[meli] fetching resource_type=pack resource_id=%s", pack_id)
    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="pack",
        resource_id=pack_id,
        headers=headers,
    ).to_legacy()


def get_claim(integration: Dict, claim_id: str) -> Dict:
    """Fetch a Post Purchase claim by its typed claim identifier."""
    headers = _auth_headers(integration)
    claim_id = _sanitize_resource_id(claim_id, resource_name="claim")
    url = _ml_url(f"/post-purchase/v1/claims/{claim_id}")
    logger.info("[meli] fetching resource_type=claim resource_id=%s", claim_id)
    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="claim",
        resource_id=claim_id,
        headers=headers,
    ).to_legacy()


def get_claim_returns(integration: Dict, claim_id: str) -> Dict:
    """Fetch the return entity related to a Post Purchase claim."""
    headers = _auth_headers(integration)
    claim_id = _sanitize_resource_id(claim_id, resource_name="claim")
    url = _ml_url(f"/post-purchase/v2/claims/{claim_id}/returns")
    logger.info("[meli] fetching resource_type=return claim_id=%s", claim_id)
    return request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="return",
        resource_id=claim_id,
        headers=headers,
    ).to_legacy()

def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    """
    Fetches list of orders from Mercado Livre API for a given integration instance.
    """
    headers = _auth_headers(integration)

    # Prepare URL and parameters
    url = _ml_url("/orders/search")

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

    logger.info("[meli] fetching resource_type=orders_search")
    result = request_json(
        requests.get,
        url,
        provider="Mercado Livre",
        resource_type="orders_search",
        headers=headers,
        params=params,
    )
    if not result.ok:
        return [result.to_legacy()]
    data = result.value or {}

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

