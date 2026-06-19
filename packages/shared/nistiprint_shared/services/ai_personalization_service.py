import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.utils.resource_helper import get_prompt_template_path

logger = logging.getLogger(__name__)

ALLOWED_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
)
DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_MAX_PROCESSING = 50
CHAT_CONTEXT_LIMIT = 60
LISTING_WINDOW_DAYS = 5
STATUS_EM_ANDAMENTO = 2
PROMPT_FALLBACK_PATH = Path(get_prompt_template_path())

_httpx_client = httpx.Client(
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    timeout=httpx.Timeout(30.0, connect=5.0),
)
_genai_client = None
_shopee_channel_ids = None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _parse_json_if_needed(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _truncate(value: Any, max_len: int = 1000):
    if value is None or not isinstance(value, str):
        return value
    return value[:max_len] + "..." if len(value) > max_len else value


def _truncate_json(data: Any, max_len: int = 5000):
    if data is None:
        return None
    payload = json.dumps(data, ensure_ascii=False, default=str)
    if len(payload) > max_len:
        return payload[:max_len] + "... [TRUNCATED]"
    return data


def _load_prompt_fallback() -> str:
    try:
        return PROMPT_FALLBACK_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Falha ao ler prompt fallback em %s: %s", PROMPT_FALLBACK_PATH, exc)
        return (
            "Voce e um assistente especialista em extrair dados de personalizacao de pedidos.\n"
            "Analise os dados do pedido e o historico do chat abaixo e retorne APENAS um JSON valido."
        )


def load_prompt_template() -> str:
    prompt = app_config_service.get_config("prompt_template")
    if isinstance(prompt, dict):
        prompt = prompt.get("text")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()

    env_prompt = os.environ.get("AI_PROMPT_TEMPLATE")
    if env_prompt and env_prompt.strip():
        return env_prompt.strip()

    return _load_prompt_fallback()


def get_model_name() -> str:
    configured_model = app_config_service.get_config("model_name")
    if isinstance(configured_model, str):
        configured_model = configured_model.strip().replace('"', "")
    if configured_model in ALLOWED_MODELS:
        return configured_model
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def get_max_processing() -> int:
    configured_limit = app_config_service.get_config("max_processing")
    try:
        return max(1, int(configured_limit))
    except (TypeError, ValueError):
        return DEFAULT_MAX_PROCESSING


def get_ai_config() -> Dict[str, Any]:
    return {
        "prompt_template": load_prompt_template(),
        "model_name": get_model_name(),
        "max_processing": get_max_processing(),
        "allowed_models": list(ALLOWED_MODELS),
    }


def update_ai_config(prompt_template=None, model_name=None, max_processing=None) -> Dict[str, Any]:
    if prompt_template is not None:
        app_config_service.set_config("prompt_template", prompt_template)

    if model_name is not None:
        if model_name not in ALLOWED_MODELS:
            raise ValueError(f"Modelo invalido: {model_name}")
        app_config_service.set_config("model_name", model_name)

    if max_processing is not None:
        try:
            validated = max(1, int(max_processing))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_processing invalido") from exc
        app_config_service.set_config("max_processing", validated)

    return get_ai_config()


def _get_genai_client():
    global _genai_client
    if _genai_client is not None:
        return _genai_client

    from dotenv import find_dotenv
    # Imprime o caminho exato do arquivo .env que o Python está carregando
    print("Caminho do .env:", find_dotenv())

    # Força o carregamento e sobrescreve variáveis antigas da memória
    # load_dotenv(override=True)
    api_key = os.getenv("NISTIPRINT_AI_KEY")
    print(api_key[-4:])
    if not api_key:
        raise RuntimeError("NISTIPRINT_AI_KEY nao configurada")

    try:
        from google import genai
    except Exception as exc:  # pragma: no cover - depende de ambiente
        raise RuntimeError(f"Falha ao importar cliente Gemini: {exc}") from exc

    _genai_client = genai.Client(api_key=api_key)
    return _genai_client


def run_model(prompt_payload: str) -> Dict[str, Any]:
    client = _get_genai_client()
    prompt = f"{load_prompt_template()}\n\n{prompt_payload}"
    response = client.models.generate_content(
        model=get_model_name(),
        contents=prompt,
    )
    if not response or not response.text:
        raise ValueError("Resposta vazia do modelo")

    text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def _normalize_order_row(row: Dict[str, Any]) -> Dict[str, Any]:
    contato = _parse_json_if_needed(row.get("contato"), {}) or {}
    buyer_info = _parse_json_if_needed(row.get("informacoes_comprador"), {}) or {}
    items = _parse_json_if_needed(row.get("itens"), []) or []
    return {
        "id": row.get("id"),
        "order_id": row.get("numero_pedido"),
        "shopee_order_sn": row.get("numero_loja"),
        "bling_id": row.get("bling_id"),
        "order_date": row.get("data_pedido"),
        "message_to_seller": row.get("shopee_message") or "",
        "items": items,
        "buyer_info": buyer_info,
        "buyer_username": row.get("buyer_username") or buyer_info.get("username") or "",
        "contato": contato,
        "nome_cliente": row.get("nome_cliente") or contato.get("nome") or "",
        "has_chat_messages": row.get("has_chat_messages", False),
        "has_buyer_message": row.get("has_buyer_message", bool((row.get("shopee_message") or "").strip())),
        "personalizado": row.get("personalizado", True),
        "deletado": row.get("deletado", False),
        "situacao_pedido_id": row.get("situacao_pedido_id"),
        "last_ai_executed_at": row.get("last_ai_executed_at"),
        "last_buyer_message_at": row.get("last_buyer_message_at"),
        "last_chat_message_at": row.get("last_chat_message_at"),
        "needs_ai_processing": row.get("needs_ai_processing"),
        "ai_status": row.get("ai_status"),
    }


def should_process_order(order: Dict[str, Any], force: bool = False) -> bool:
    if force:
        return True
    if "needs_ai_processing" in order and order.get("needs_ai_processing") is not None:
        return bool(order.get("needs_ai_processing"))

    last_ai_executed_at = _parse_datetime(order.get("last_ai_executed_at"))
    last_buyer_message_at = _parse_datetime(order.get("last_buyer_message_at"))
    has_message_to_seller = bool((order.get("message_to_seller") or "").strip())
    ai_status = (order.get("ai_status") or "").lower()

    if not has_message_to_seller and last_buyer_message_at is None:
        return False
    if last_ai_executed_at is None:
        return True
    if ai_status in {"error", "db_error", "no_response"}:
        return True
    return bool(last_buyer_message_at and last_buyer_message_at > last_ai_executed_at)


def _get_shopee_channel_ids():
    global _shopee_channel_ids
    if _shopee_channel_ids is not None:
        return _shopee_channel_ids

    response = (
        supabase_db.table("canais_venda")
        .select("id")
        .eq("slug", "shopee")
        .execute()
    )
    if not response.data:
        raise RuntimeError("Canal de venda Shopee nao encontrado")

    _shopee_channel_ids = [row["id"] for row in response.data if row.get("id") is not None]
    if not _shopee_channel_ids:
        raise RuntimeError("Canal de venda Shopee nao encontrado")
    return _shopee_channel_ids


def _extract_buyer_username(buyer_info: Dict[str, Any], fallback: str = "") -> str:
    if not isinstance(buyer_info, dict):
        return fallback or ""
    return (
        buyer_info.get("username")
        or buyer_info.get("user_name")
        or buyer_info.get("buyer_username")
        or fallback
        or ""
    )


def _fetch_recent_personalized_orders(
    order_sn=None,
    pedido_ids=None,
    limit=None,
    recent_days: Optional[int] = None,
):
    query = (
        supabase_db.table("pedidos")
        .select(
            "id,numero_pedido,codigo_pedido_externo,data_venda,informacoes_cliente,"
            "cliente_nome,cliente_documento,cliente_telefone,cliente_email,canal_venda_id,"
            "situacao_pedido_id,buyer_username,marketplace_order_id,message_to_seller,"
            "shipping_carrier,contact_marketplace_id"
        )
        .in_("canal_venda_id", _get_shopee_channel_ids())
        .eq("situacao_pedido_id", STATUS_EM_ANDAMENTO)
        .order("data_venda", desc=True)
    )

    if order_sn:
        query = query.eq("codigo_pedido_externo", str(order_sn))
    elif pedido_ids:
        query = query.in_("id", pedido_ids)
    elif recent_days:
        cutoff = datetime.now() - timedelta(days=recent_days)
        query = query.gte("data_venda", cutoff.isoformat())

    if limit and not pedido_ids and not order_sn:
        query = query.limit(max(limit * 4, limit, 150))

    return query.execute().data or []


def _fetch_chat_stats_by_username(usernames: List[str], order_dates: List[Any]) -> Dict[str, Dict[str, Any]]:
    usernames = [username for username in usernames if username]
    if not usernames:
        return {}

    parsed_dates = [_parse_datetime(value) for value in order_dates]
    parsed_dates = [value for value in parsed_dates if value]
    if parsed_dates:
        cutoff = min(parsed_dates) - timedelta(days=7)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    stats = {}
    seen_ids = set()

    def consume(rows):
        for row in rows or []:
            row_id = row.get("id")
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)

            created_at = _parse_datetime(row.get("created_at"))
            if not created_at:
                continue

            for username, key in (
                (row.get("from_user_name"), "buyer"),
                (row.get("to_user_name"), "chat"),
            ):
                if username not in usernames:
                    continue

                current = stats.setdefault(username, {
                    "last_chat_message_at": None,
                    "last_buyer_message_at": None,
                    "has_chat_messages": False,
                })
                current["has_chat_messages"] = True

                if not current["last_chat_message_at"] or created_at > current["last_chat_message_at"]:
                    current["last_chat_message_at"] = created_at
                if key == "buyer" and (
                    not current["last_buyer_message_at"]
                    or created_at > current["last_buyer_message_at"]
                ):
                    current["last_buyer_message_at"] = created_at

    from_rows = (
        supabase_db.table("mensagem_chat_shopee")
        .select("id,from_user_name,to_user_name,created_at")
        .in_("from_user_name", usernames)
        .gte("created_at", cutoff.isoformat())
        .execute()
        .data
        or []
    )
    consume(from_rows)

    to_rows = (
        supabase_db.table("mensagem_chat_shopee")
        .select("id,from_user_name,to_user_name,created_at")
        .in_("to_user_name", usernames)
        .gte("created_at", cutoff.isoformat())
        .execute()
        .data
        or []
    )
    consume(to_rows)

    return stats


def _assemble_orders(
    order_sn=None,
    pedido_ids=None,
    limit=None,
    recent_days: Optional[int] = LISTING_WINDOW_DAYS,
):
    base_orders = _fetch_recent_personalized_orders(
        order_sn=order_sn,
        pedido_ids=pedido_ids,
        limit=limit,
        recent_days=recent_days,
    )
    if not base_orders:
        return []

    order_ids = [row["id"] for row in base_orders]
    order_map = {row["id"]: row for row in base_orders}

    items = (
        supabase_db.table("itens_pedido")
        .select("id,pedido_id,sku_externo,descricao,quantidade,preco_unitario,produto_id,personalizado")
        .in_("pedido_id", order_ids)
        .eq("personalizado", True)
        .order("id", desc=False)
        .execute()
        .data
        or []
    )
    if not items:
        return []

    items_by_order = {}
    for item in items:
        items_by_order.setdefault(item["pedido_id"], []).append(item)

    filtered_order_ids = [pedido_id for pedido_id in order_ids if pedido_id in items_by_order]
    filtered_orders = [order_map[pedido_id] for pedido_id in filtered_order_ids]
    if not filtered_orders:
        return []

    order_sns = [str(order["codigo_pedido_externo"]) for order in filtered_orders if order.get("codigo_pedido_externo")]
    numeros_pedido = [str(order["numero_pedido"]) for order in filtered_orders if order.get("numero_pedido")]

    bling_map = {}
    if numeros_pedido:
        bling_rows = (
            supabase_db.table("pedidos_bling")
            .select("numero_pedido,bling_id")
            .in_("numero_pedido", numeros_pedido)
            .execute()
            .data
            or []
        )
        bling_map = {str(row["numero_pedido"]): row for row in bling_rows}

    personalizations_by_item = {}
    personalizations_by_desc = {}
    if order_sns:
        personalization_rows = (
            supabase_db.table("personalizacoes_pedido")
            .select("*")
            .in_("shopee_order_sn", order_sns)
            .order("id", desc=False)
            .execute()
            .data
            or []
        )
        for personalization in personalization_rows:
            item_pedido_id = personalization.get("item_pedido_id")
            if item_pedido_id is not None:
                personalizations_by_item.setdefault(item_pedido_id, []).append(personalization)

            key = (
                str(personalization.get("shopee_order_sn") or ""),
                str(personalization.get("item_description") or "").strip(),
            )
            personalizations_by_desc.setdefault(key, []).append(personalization)

    latest_logs = {}
    if order_sns:
        log_rows = (
            supabase_db.table("logs_execucao_ia")
            .select("id,order_sn,executed_at,status")
            .in_("order_sn", order_sns)
            .order("executed_at", desc=True)
            .execute()
            .data
            or []
        )
        for log in log_rows:
            latest_logs.setdefault(str(log["order_sn"]), log)

    usernames = []
    order_dates = []
    for order in filtered_orders:
        contato = _parse_json_if_needed(order.get("informacoes_cliente"), {}) or {}
        buyer_info = {"username": order.get("buyer_username") or contato.get("username") or contato.get("buyer_username")}
        usernames.append(_extract_buyer_username(buyer_info, fallback=order.get("cliente_nome") or contato.get("nome") or ""))
        order_dates.append(order.get("data_venda"))

    chat_stats_by_username = _fetch_chat_stats_by_username(usernames, order_dates)

    assembled = []
    for order in filtered_orders:
        order_sn_value = str(order.get("codigo_pedido_externo") or "")
        contato = _parse_json_if_needed(order.get("informacoes_cliente"), {}) or {}
        buyer_info = {
            "username": order.get("buyer_username") or contato.get("username") or contato.get("buyer_username"),
            "marketplace_order_id": order.get("marketplace_order_id"),
            "contact_marketplace_id": order.get("contact_marketplace_id"),
        }
        buyer_username = _extract_buyer_username(
            buyer_info,
            fallback=order.get("cliente_nome") or contato.get("nome") or "",
        )
        chat_stats = chat_stats_by_username.get(buyer_username, {})
        latest_log = latest_logs.get(order_sn_value, {})
        order_items = []

        for item in items_by_order.get(order["id"], []):
            item_personalizations = personalizations_by_item.get(item["id"])
            if item_personalizations is None:
                item_personalizations = personalizations_by_desc.get(
                    (order_sn_value, str(item.get("descricao") or "").strip()),
                    [],
                )
            order_items.append({
                "id": item.get("id"),
                "codigo": item.get("sku_externo"),
                "descricao": item.get("descricao"),
                "quantidade": item.get("quantidade"),
                "valor": item.get("preco_unitario"),
                "unidade": "UN",
                "personalizado": item.get("personalizado", False),
                "produto": {"id": item.get("produto_id")},
                "personalizations": item_personalizations or [],
            })

        last_ai_executed_at = latest_log.get("executed_at")
        last_buyer_message_at = chat_stats.get("last_buyer_message_at")
        ai_status = latest_log.get("status") or "NOT_PROCESSED"
        message_to_seller = order.get("message_to_seller") or ""
        has_buyer_signal = bool(message_to_seller.strip()) or bool(last_buyer_message_at)

        assembled.append({
            "id": order["id"],
            "numero_pedido": order.get("numero_pedido"),
            "numero_loja": order_sn_value,
            "data_pedido": order.get("data_venda"),
            "contato": contato,
            "nome_cliente": order.get("cliente_nome") or contato.get("nome") or "",
            "bling_id": (bling_map.get(str(order.get("numero_pedido"))) or {}).get("bling_id"),
            "personalizado": True,
            "deletado": False,
            "situacao_pedido_id": order.get("situacao_pedido_id"),
            "informacoes_comprador": buyer_info,
            "shopee_message": message_to_seller,
            "buyer_username": buyer_username,
            "has_chat_messages": bool(chat_stats.get("has_chat_messages")),
            "last_chat_message_at": chat_stats.get("last_chat_message_at").isoformat() if chat_stats.get("last_chat_message_at") else None,
            "last_buyer_message_at": last_buyer_message_at.isoformat() if last_buyer_message_at else None,
            "last_ai_executed_at": last_ai_executed_at,
            "ai_status": ai_status,
            "has_buyer_message": has_buyer_signal,
            "needs_ai_processing": should_process_order({
                "last_ai_executed_at": last_ai_executed_at,
                "last_buyer_message_at": last_buyer_message_at.isoformat() if last_buyer_message_at else None,
                "ai_status": ai_status,
                "message_to_seller": message_to_seller,
            }),
            "itens": order_items,
        })

    return assembled


def select_orders_for_processing(order_sn=None, pedido_ids=None, limit=None, force=False):
    normalized_limit = None
    if limit not in (None, 0):
        normalized_limit = max(1, int(limit))

    rows = _assemble_orders(
        order_sn=order_sn,
        pedido_ids=pedido_ids,
        limit=normalized_limit,
        recent_days=None,
    )
    to_process = []
    skipped = []

    for row in rows:
        normalized = _normalize_order_row(row)
        if should_process_order(normalized, force=force):
            to_process.append({
                "id": normalized["id"],
                "order_sn": normalized["shopee_order_sn"],
                "ai_status": normalized.get("ai_status"),
            })
        else:
            skipped.append({
                "id": normalized["id"],
                "order_sn": normalized["shopee_order_sn"],
                "reason": "up_to_date",
            })

    if normalized_limit and not pedido_ids and not order_sn:
        to_process = to_process[:normalized_limit]

    return to_process, skipped


def _fetch_chat_messages(buyer_username: str, order_date=None, last_ai_executed_at=None) -> List[Dict[str, Any]]:
    if not buyer_username:
        return []

    cutoff = _parse_datetime(last_ai_executed_at)
    if cutoff:
        cutoff = cutoff - timedelta(days=1)
    else:
        order_dt = _parse_datetime(order_date)
        if order_dt:
            cutoff = order_dt - timedelta(days=1)
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    query = (
        supabase_db.table("view_mensagens_chat_ai")
        .select("*")
        .or_(f"from_user_name.eq.{buyer_username},to_user_name.eq.{buyer_username}")
        .gte("created_at", cutoff.isoformat())
        .order("created_at", desc=False)
        .limit(CHAT_CONTEXT_LIMIT)
    )
    rows = query.execute().data or []
    return compact_chat_messages(rows, buyer_username)


def _sanitize_chat_message_for_llm(content: str, sender_role: str) -> str:
    normalized = re.sub(r"\s+", " ", (content or "")).strip()
    if not normalized:
        return ""

    if sender_role == "Vendedor":
        normalized = re.sub(
            r"(?i)\s*seu pedido entrou para fila de producao.*$",
            "",
            normalized,
        ).strip()
        normalized = re.sub(
            r"(?i)\s*seu pedido entrou para fila de produção.*$",
            "",
            normalized,
        ).strip()
        if normalized.lower() in {
            "boa tarde",
            "bom dia",
            "boa noite",
            "ola",
            "olá",
            "ok",
            "obrigada",
            "obrigado",
        }:
            return ""

    return normalized[:500]


def compact_chat_messages(messages: List[Dict[str, Any]], buyer_username: str) -> List[Dict[str, Any]]:
    compacted = []
    for row in messages:
        display_content = (row.get("display_content") or "").strip()
        if not display_content:
            continue
        sender_role = "Comprador" if row.get("from_user_name") == buyer_username else "Vendedor"
        sanitized_content = _sanitize_chat_message_for_llm(display_content, sender_role)
        if not sanitized_content:
            continue

        compacted.append({
            "id": str(row.get("id")),
            "from_user_name": row.get("from_user_name") or "",
            "to_user_name": row.get("to_user_name") or "",
            "created_at": row.get("created_at"),
            "type": row.get("type") or "text",
            "display_content": sanitized_content,
            "sender_role": sender_role,
        })

    return compacted


def _load_order_for_ai(pedido_id: int) -> Dict[str, Any]:
    rows = _assemble_orders(pedido_ids=[pedido_id], recent_days=None)
    if not rows:
        raise ValueError(f"Pedido {pedido_id} nao encontrado na view de personalizados")

    normalized = _normalize_order_row(rows[0])
    normalized["chat_messages"] = _fetch_chat_messages(
        buyer_username=normalized.get("buyer_username", ""),
        order_date=normalized.get("order_date"),
        last_ai_executed_at=normalized.get("last_ai_executed_at"),
    )
    return normalized


def generate_prompt_payload(order: Dict[str, Any]) -> str:
    payload = [">>> ORDER DATA"]
    payload.append(f"  Order ID: {order.get('order_id')}")
    if order.get("bling_id"):
        payload.append(f"  Bling ID: {order.get('bling_id')}")
    payload.append(f"  Shopee Order SN: {order.get('shopee_order_sn')}")
    payload.append(f"  Order Date: {order.get('order_date')}")

    payload.append("\n>>> ITEMS:")
    for item in order.get("items") or []:
        payload.append(f"  Item ID: {item.get('id')}")
        payload.append(f"  {int(item.get('quantidade', 1))}x {item.get('descricao')}")

    payload.append("\n>>> MESSAGE TO SELLER:")
    payload.append(f"  {order.get('message_to_seller') or '[No message to seller]'}")

    payload.append("\n>>> CHAT MESSAGES:")
    messages = order.get("chat_messages") or []
    if not messages:
        payload.append("  [No chat messages for this order]")
    else:
        for msg in messages:
            payload.append(
                f"[{msg.get('id')}][{msg.get('created_at')}] "
                f"{msg.get('sender_role')}: {msg.get('display_content')}"
            )

    return "\n".join(payload)


def _persistir_personalizacao(order: Dict[str, Any], result: Dict[str, Any]):
    shopee_order_sn = str(order["shopee_order_sn"])
    items_by_id = {str(item.get("id")): item for item in (order.get("items") or [])}
    now_iso = datetime.now(timezone.utc).isoformat()

    supabase_db.table("personalizacoes_pedido").delete().eq("shopee_order_sn", shopee_order_sn).execute()

    records = []
    for item in result.get("personalized_items", []):
        item_id = str(item.get("item_id", "") or "")
        matched_item = items_by_id.get(item_id)
        details = {
            "quantity_to_personalize": item.get("quantity_to_personalize", 1),
            "initial_source_message_id": item.get("initial_source_message_id"),
        }
        records.append({
            "codigo_pedido": shopee_order_sn,
            "shopee_order_sn": shopee_order_sn,
            "bling_id": str(order.get("bling_id") or ""),
            "item_pedido_id": matched_item.get("id") if matched_item else None,
            "item_id": item_id or None,
            "item_description": item.get("item_description") or (matched_item or {}).get("descricao"),
            "customization_name": _truncate(item.get("customization_name"), 500),
            "customization_initial": _truncate(item.get("customization_initial"), 100),
            "name_source_message_id": str(item.get("name_source_message_id")) if item.get("name_source_message_id") else None,
            "status": result.get("status", "SUCCESS"),
            "reasoning": _truncate(result.get("reasoning"), 1500),
            "detalhes_personalizacao": details,
            "metadata": {
                "source": get_model_name(),
                "processed_at": now_iso,
                "quantity_to_personalize": details["quantity_to_personalize"],
                "initial_source_message_id": details["initial_source_message_id"],
            },
            "updated_at": now_iso,
        })

    if records:
        supabase_db.table("personalizacoes_pedido").insert(records).execute()


def log_ai_execution(order_sn, input_data, chat_context, status, result=None, error_message=None, metadata=None):
    log_record = {
        "order_sn": order_sn,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "input_data": _truncate(input_data, 25000),
        "chat_context": _truncate_json(chat_context, 12000),
        "extracted_personalization": _truncate_json((result or {}).get("personalized_items"), 12000) if isinstance(result, dict) else None,
        "model_result": _truncate_json(result, 15000),
        "status": status,
        "error_message": _truncate(error_message, 1000),
        "metadata": metadata or {
            "model_name": get_model_name(),
        },
    }
    try:
        supabase_db.table("logs_execucao_ia").insert(log_record).execute()
    except Exception as exc:
        logger.error("Erro ao salvar log de IA para %s: %s", order_sn, exc)


def _process_single_order_sync(pedido_id: int, force: bool = False):
    order = _load_order_for_ai(pedido_id)
    order_sn = order["shopee_order_sn"]

    if not should_process_order(order, force=force):
        return {
            "success": True,
            "status": "up_to_date",
            "order_sn": order_sn,
            "message": "Pedido ja esta atualizado para IA.",
        }

    prompt_payload = generate_prompt_payload(order)
    chat_context = order.get("chat_messages") or []

    try:
        result = run_model(prompt_payload)
        _persistir_personalizacao(order, result)
        log_ai_execution(order_sn, prompt_payload, chat_context, "success", result=result)
        return {
            "success": True,
            "status": "success",
            "order_sn": order_sn,
            "message": "Pedido processado com sucesso.",
            "result": result,
        }
    except Exception as exc:
        logger.error("Erro ao processar pedido %s: %s", pedido_id, exc, exc_info=True)
        log_ai_execution(order_sn, prompt_payload, chat_context, "error", error_message=str(exc))
        return {
            "success": False,
            "status": "error",
            "order_sn": order_sn,
            "message": str(exc),
        }


def create_processing_batch(pedido_ids: List[int], skipped=None):
    batch_res = supabase_db.table("execucoes_ai_batch").insert({
        "pedido_ids": pedido_ids,
        "total": len(pedido_ids),
        "status": "PENDENTE",
    }).execute()
    if not batch_res.data:
        raise RuntimeError("Falha ao criar batch de IA")

    batch_id = batch_res.data[0]["id"]
    processar_batch_ia.delay(batch_id)
    return {
        "batch_id": batch_id,
        "total": len(pedido_ids),
        "skipped": skipped or [],
    }


@shared_task(name="services.ai_personalization.processar_batch", bind=True)
def processar_batch_ia(self, batch_id: str):
    batch = supabase_db.table("execucoes_ai_batch").select("*").eq("id", batch_id).single().execute().data
    if not batch:
        return

    supabase_db.table("execucoes_ai_batch").update({"status": "RODANDO"}).eq("id", batch_id).execute()

    for pedido_id in batch["pedido_ids"]:
        processar_pedido_ia.apply_async(
            args=[batch_id, pedido_id],
            queue="ai_personalization",
        )


@shared_task(name="services.ai_personalization.processar_pedido", bind=True, max_retries=2)
def processar_pedido_ia(self, batch_id: str, pedido_id: int):
    started_at = time.monotonic()
    status = "OK"
    error_message = None

    try:
        result = _process_single_order_sync(pedido_id)
        if result["status"] == "up_to_date":
            status = "UP_TO_DATE"
        elif not result["success"]:
            status = "ERRO"
            error_message = result["message"]
    except httpx.PoolTimeout as exc:
        raise self.retry(exc=exc, countdown=30)
    except Exception as exc:  # pragma: no cover - protecao de tarefa
        status = "ERRO"
        error_message = str(exc)
        logger.error("Erro inesperado em processar_pedido_ia %s: %s", pedido_id, exc, exc_info=True)
    finally:
        supabase_db.table("execucoes_ai_item").insert({
            "batch_id": batch_id,
            "pedido_id": pedido_id,
            "status": status,
            "erro": _truncate(error_message, 500),
            "duracao_ms": int((time.monotonic() - started_at) * 1000),
        }).execute()

        supabase_db.rpc("incrementar_batch_ia", {
            "p_batch_id": batch_id,
            "p_sucesso": 1 if status in {"OK", "UP_TO_DATE"} else 0,
            "p_falha": 1 if status == "ERRO" else 0,
        }).execute()


def process_orders(limit=None, order_sn=None, pedido_ids=None, force=False):
    effective_limit = limit
    if limit in (0, "0", ""):
        effective_limit = None

    candidates, skipped = select_orders_for_processing(
        order_sn=order_sn,
        pedido_ids=pedido_ids,
        limit=effective_limit,
        force=force,
    )

    if order_sn and candidates:
        single = _process_single_order_sync(candidates[0]["id"], force=force)
        return single["success"], single["message"], {
            "processed": [single["order_sn"]],
            "skipped": skipped,
            "status": single["status"],
            "result": single.get("result"),
        }

    if not candidates:
        return True, "Nada a processar.", {
            "processed": [],
            "skipped": skipped,
            "status": "up_to_date" if skipped else "empty",
        }

    batch = create_processing_batch([row["id"] for row in candidates], skipped=skipped)
    return True, f"Lote de {batch['total']} pedido(s) agendado.", batch


def get_logs_by_order_sn(order_sn):
    return (
        supabase_db.table("logs_execucao_ia")
        .select("*")
        .eq("order_sn", order_sn)
        .order("executed_at", desc=True)
        .execute()
        .data
        or []
    )


def get_all_logs(order_sn=None, status=None, limit=50, offset=0):
    query = supabase_db.table("logs_execucao_ia").select("*", count="exact")
    if order_sn:
        query = query.eq("order_sn", order_sn)
    if status:
        query = query.eq("status", status)
    response = query.order("executed_at", desc=True).range(offset, offset + max(0, limit - 1)).execute()
    return {
        "logs": response.data or [],
        "total": response.count or 0,
    }


def delete_logs(order_sn=None, status=None, delete_all=False):
    if not delete_all and not order_sn and not status:
        raise ValueError("Informe um filtro para deletar logs ou use all=true")

    query = supabase_db.table("logs_execucao_ia").delete()
    if order_sn:
        query = query.eq("order_sn", order_sn)
    if status:
        query = query.eq("status", status)

    response = query.execute()
    return len(response.data or [])


def save_feedback(order_sn, avaliacao, texto_feedback=""):
    payload = {
        "codigo_pedido": str(order_sn),
        "avaliacao": int(avaliacao),
        "texto_feedback": texto_feedback or "",
        "updated_at": datetime.utcnow().isoformat(),
    }
    supabase_db.table("feedback_pedido").insert(payload).execute()
    return payload


def get_chat_messages(username, limit=None):
    if not username:
        return []
    query = (
        supabase_db.table("view_mensagens_chat_ai")
        .select("*")
        .or_(f"from_user_name.eq.{username},to_user_name.eq.{username}")
        .order("created_at", desc=False)
    )
    if limit:
        query = query.limit(limit)
    messages = query.execute().data or []
    return compact_chat_messages(messages, username)


def get_orders_with_chats(order_sn=None, limit=None):
    rows = _assemble_orders(
        order_sn=order_sn,
        limit=limit,
        recent_days=None,
    )
    normalized_orders = [_normalize_order_row(row) for row in rows]
    if limit:
        return normalized_orders[:limit]
    return normalized_orders
