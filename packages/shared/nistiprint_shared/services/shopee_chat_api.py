"""SellerChat Open API client used by recovery and reconciliation jobs."""
import time
from typing import Dict, Optional, Sequence
import requests
from nistiprint_shared.services.platform_drivers.shopee import _generate_sign, _resolve_credentials


def get_chat_messages(integration: Dict, conversation_id: str, *, page_size: int = 20,
                      offset: Optional[str] = None, message_id_list: Optional[Sequence[str]] = None,
                      business_type: int = 0, timeout_seconds: float = 10.0) -> Dict:
    host = "https://partner.shopeemobile.com"
    path = "/api/v2/sellerchat/get_message"
    resolved = _resolve_credentials(integration)
    if not all(resolved.values()):
        return {"error": "Configuracao da Shopee incompleta para SellerChat."}
    partner_id, shop_id = int(resolved["partner_id"]), int(resolved["shop_id"])
    timestamp = int(time.time())
    params = {"partner_id": partner_id, "timestamp": timestamp,
              "sign": _generate_sign(partner_id, resolved["partner_key"], path, timestamp,
                                      resolved["access_token"], shop_id),
              "access_token": resolved["access_token"], "shop_id": shop_id,
              "conversation_id": str(conversation_id), "page_size": max(1, min(int(page_size), 100)),
              "business_type": int(business_type)}
    if offset not in (None, ""):
        params["offset"] = str(offset)
    if message_id_list:
        params["message_id_list"] = [str(item) for item in message_id_list]
    try:
        response = requests.get(f"{host}{path}", params=params, timeout=timeout_seconds)
    except requests.Timeout as exc:
        return {"error": str(exc) or "Timeout na API SellerChat", "error_type": "timeout", "retryable": True}
    except requests.RequestException as exc:
        return {"error": str(exc), "error_type": "network_error", "retryable": True}
    if response.status_code != 200:
        status = response.status_code
        if status == 429:
            error_type, retryable = "rate_limit", True
        elif status in (401, 403):
            error_type, retryable = "authentication_error", False
        elif status == 400:
            error_type, retryable = "parameter_error", False
        else:
            error_type, retryable = "server_error", status >= 500
        return {"error": f"Erro na API SellerChat: {status}", "error_type": error_type,
                "retryable": retryable, "details": response.text}
    data = response.json()
    if data.get("error"):
        code = str(data.get("error") or "")
        retryable_codes = {"error_network", "internal_server_error", "error_server", "system_busy", "error_rate_limit"}
        auth_codes = {"error_auth", "error_sign", "invalid_acceess_token", "error_api_permission"}
        error_type = "authentication_error" if code in auth_codes else ("transient_api_error" if code in retryable_codes else "parameter_error")
        return {"error": data.get("message") or "Erro reportado pela Shopee", "code": code,
                "error_type": error_type, "retryable": code in retryable_codes, "details": data}
    body = data.get("response") or data.get("data") or data
    if isinstance(body, list):
        return {"messages": body, "raw": data}
    page_result = body.get("page_result") if isinstance(body.get("page_result"), dict) else {}
    return {"messages": body.get("messages") or body.get("message_list") or [],
            "next_offset": page_result.get("next_offset"), "page_size": page_result.get("page_size"),
            "raw": data}


def get_all_chat_messages(integration: Dict, conversation_id: str, *, page_size: int = 100,
                          business_type: int = 0, max_pages: int = 100) -> Dict:
    messages, offset, seen_offsets = [], None, set()
    for _ in range(max(1, int(max_pages))):
        page = get_chat_messages(integration, conversation_id, page_size=page_size,
                                 offset=offset, business_type=business_type)
        if page.get("error"):
            return {**page, "messages": messages}
        messages.extend(page.get("messages") or [])
        next_offset = page.get("next_offset")
        if next_offset in (None, ""):
            return {"messages": messages, "next_offset": None, "complete": True}
        next_offset = str(next_offset)
        if next_offset in seen_offsets:
            return {"error": "Paginacao SellerChat repetiu next_offset", "error_type": "pagination_loop",
                    "retryable": False, "messages": messages, "next_offset": next_offset}
        seen_offsets.add(next_offset)
        offset = next_offset
    return {"error": "Limite de paginas SellerChat atingido", "error_type": "page_limit",
            "retryable": True, "messages": messages, "next_offset": offset}
