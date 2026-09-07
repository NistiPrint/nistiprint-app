"""SellerChat Open API client used by recovery and reconciliation jobs."""
import time
from typing import Dict, Optional, Sequence
import requests
from nistiprint_shared.services.platform_drivers.shopee import (
    SHOPEE_AUTH_CODES,
    SHOPEE_TRANSIENT_CODES,
    _generate_sign,
    _resolve_credentials,
)

# Documentado em v2.sellerchat.get_message: "default 25, maximum is 60".
# Pedir mais que isso e `param_error`, nao truncamento.
PAGE_SIZE_MAXIMO = 60


def _erro_sellerchat(response, data: Optional[Dict], codigo: str) -> Dict:
    """Classifica pelo codigo da Shopee antes do status HTTP.

    A Shopee usa 491, que nao e status HTTP padrao, e poe o motivo real no corpo:
    `{"error":"param_error","message":"Error or loss in request parameter."}`.
    Classificar pelo status faria um erro de parametro -- permanente, so o codigo
    conserta -- ser tratado como limite de taxa e repetido para sempre.
    """
    status = getattr(response, "status_code", 0)
    retry_after = None
    headers = getattr(response, "headers", {})
    if isinstance(headers, dict) and headers.get("Retry-After"):
        try:
            retry_after = max(1, int(headers["Retry-After"]))
        except (TypeError, ValueError):
            retry_after = None

    if codigo:
        if codigo in SHOPEE_AUTH_CODES:
            error_type, retryable = "authentication_error", False
        elif codigo in SHOPEE_TRANSIENT_CODES:
            error_type, retryable = "transient_api_error", True
        else:
            error_type, retryable = "parameter_error", False
    elif status == 429:
        error_type, retryable = "rate_limit", True
    elif status in (401, 403):
        error_type, retryable = "authentication_error", False
    elif status == 400:
        error_type, retryable = "parameter_error", False
    elif data is None and status == 200:
        error_type, retryable = "invalid_response", True
    else:
        error_type, retryable = "server_error", status >= 500

    detalhe = (data or {}).get("message") if isinstance(data, dict) else None
    corpo = (getattr(response, "text", "") or "")[:500]
    mensagem = detalhe or corpo or f"Erro na API SellerChat: {status}"
    return {"error": f"[HTTP {status}] {mensagem}", "code": codigo or None,
            "error_type": error_type, "retryable": retryable,
            "retry_after": retry_after, "status_code": status,
            "details": data if data is not None else corpo}


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
              "conversation_id": str(conversation_id),
              "page_size": max(1, min(int(page_size), PAGE_SIZE_MAXIMO)),
              "business_type": int(business_type)}
    if offset not in (None, ""):
        params["offset"] = str(offset)
    if message_id_list:
        # Array vai separado por virgula, como em `order_sn_list` do
        # get_order_detail -- que e a chamada Shopee que ja funciona em producao
        # neste codigo. Passar a lista crua faz o `requests` repetir a chave
        # (`message_id_list=a&message_id_list=b`), e a Shopee responde
        # `param_error` com HTTP 491.
        params["message_id_list"] = ",".join(str(item) for item in message_id_list)
    try:
        response = requests.get(f"{host}{path}", params=params, timeout=timeout_seconds)
    except requests.Timeout as exc:
        return {"error": str(exc) or "Timeout na API SellerChat", "error_type": "timeout", "retryable": True}
    except requests.RequestException as exc:
        return {"error": str(exc), "error_type": "network_error", "retryable": True}
    try:
        data = response.json()
    except (ValueError, requests.JSONDecodeError):
        data = None
    # Corpo que nao e um objeto JSON (array, escalar, HTML de gateway) nao tem
    # como ser lido como resposta da Shopee.
    if not isinstance(data, dict):
        data = None

    codigo = str(data.get("error") or "").strip() if data else ""
    if response.status_code != 200 or codigo or data is None:
        return _erro_sellerchat(response, data, codigo)
    body = data.get("response") or data.get("data") or data
    if isinstance(body, list):
        return {"messages": body, "raw": data}
    page_result = body.get("page_result") if isinstance(body.get("page_result"), dict) else {}
    return {"messages": body.get("messages") or body.get("message_list") or [],
            "next_offset": page_result.get("next_offset"), "page_size": page_result.get("page_size"),
            "raw": data}


def message_timestamp(row: Dict) -> Optional[int]:
    """Epoch da mensagem, aceitando os tres nomes que a Shopee usa."""
    for key in ("created_timestamp", "created_at", "timestamp"):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def get_all_chat_messages(integration: Dict, conversation_id: str, *,
                          page_size: int = PAGE_SIZE_MAXIMO,
                          business_type: int = 0, max_pages: int = 100,
                          desde_epoch: Optional[int] = None) -> Dict:
    """Percorre a conversa, opcionalmente parando ao sair da janela.

    A Shopee devolve a pagina mais recente primeiro, mas isso nao e contrato
    publicado. Por isso so paramos por janela depois de ja termos visto ao menos
    uma mensagem dentro dela: numa ordem invertida a busca degrada para varredura
    completa em vez de devolver zero mensagens.
    """
    messages, offset, seen_offsets = [], None, set()
    viu_dentro_da_janela = False
    for _ in range(max(1, int(max_pages))):
        page = get_chat_messages(integration, conversation_id, page_size=page_size,
                                 offset=offset, business_type=business_type)
        if page.get("error"):
            return {**page, "messages": messages}
        pagina = page.get("messages") or []
        messages.extend(pagina)

        if desde_epoch is not None and pagina:
            marcas = [marca for marca in (message_timestamp(row) for row in pagina)
                      if marca is not None]
            if marcas:
                if max(marcas) >= int(desde_epoch):
                    viu_dentro_da_janela = True
                elif viu_dentro_da_janela:
                    return {"messages": messages, "next_offset": None, "complete": True,
                            "parou_na_janela": True}

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
