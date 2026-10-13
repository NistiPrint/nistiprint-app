import json
import logging
import os
import re
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from celery import shared_task

from nistiprint_shared.constants import STATUS_PEDIDO_PRONTO_ENVIO
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.ai import (
    DEFAULT_MODEL_BY_PROVIDER,
    DEFAULT_PROVIDER,
    PROVIDERS,
    AIResponse,
    ai_router,
    extract_json,
    validate_model,
)
from nistiprint_shared.services.ai.gemini_provider import ALLOWED_MODELS as GEMINI_MODELS
from nistiprint_shared.utils.resource_helper import get_prompt_template_path

logger = logging.getLogger(__name__)

#: Mantido por compatibilidade com chamadores antigos. A allowlist real por
#: provedor vive em `services/ai/` — o OpenRouter nao tem lista fixa, porque o
#: catalogo dele muda toda semana.
ALLOWED_MODELS = GEMINI_MODELS
DEFAULT_MODEL = DEFAULT_MODEL_BY_PROVIDER[DEFAULT_PROVIDER]
DEFAULT_MAX_PROCESSING = 50
CHAT_CONTEXT_LIMIT = 60
CHAT_LOOKBACK_DAYS = 7
SELECTION_PAGE_SIZE = 500
SELECTION_ID_CHUNK_SIZE = 200
# Uma tentativa sincrona de fechar a conversa antes de desistir do pedido. O
# orcamento e curto de proposito: o caminho normal e a conversa ja estar completa
# porque o bundle foi resolvido no ingest. Isto aqui e excecao, nao rotina.
CHAT_GATE_TIMEOUT_SEGUNDOS = float(os.getenv("AI_CHAT_GATE_TIMEOUT_SEGUNDOS", "3"))
CHAT_GATE_ATIVO = os.getenv("AI_CHAT_GATE_ATIVO", "1").strip().lower() not in ("0", "false", "off")
STATUS_EM_ANDAMENTO = 2
STATUS_PERSONALIZACAO = [STATUS_EM_ANDAMENTO, STATUS_PEDIDO_PRONTO_ENVIO]
PROMPT_FALLBACK_PATH = Path(get_prompt_template_path())

_httpx_client = httpx.Client(
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    timeout=httpx.Timeout(30.0, connect=5.0),
)
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


def _message_from_shopee_mirror(row: Dict[str, Any]) -> str:
    """Le a observacao da compra do espelho Shopee, inclusive do payload bruto."""
    raw_payload = _parse_json_if_needed((row or {}).get("raw_payload"), {}) or {}
    for candidate in (
        (row or {}).get("mensagem"),
        raw_payload.get("message_to_seller"),
        raw_payload.get("mensagem"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


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


def load_prompt_template(overrides: Dict[str, Any] | None = None) -> str:
    prompt = (overrides or {}).get("prompt_template")
    if prompt is None:
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
    """Modelo efetivo, ja resolvido pelo roteador para o provedor ativo."""
    return ai_router.resolve_settings()["model"]


def get_provider_name() -> str:
    return ai_router.resolve_settings()["provider"]


def get_max_processing() -> int:
    configured_limit = app_config_service.get_config("max_processing")
    try:
        return max(1, int(configured_limit))
    except (TypeError, ValueError):
        return DEFAULT_MAX_PROCESSING


def get_ai_config() -> Dict[str, Any]:
    settings = ai_router.resolve_settings()
    return {
        "prompt_template": load_prompt_template(),
        "provider": settings["provider"],
        "model_name": settings["model"],
        "fallback_provider": settings["fallback_provider"],
        "timeout_seconds": settings["timeout_seconds"],
        "max_processing": get_max_processing(),
        "providers": list(PROVIDERS),
        # O Gemini tem allowlist; o OpenRouter aceita `openrouter/auto` ou
        # qualquer `vendor/model`, entao a UI deve oferecer campo livre nele.
        "allowed_models": {
            "gemini": list(GEMINI_MODELS),
            "openrouter": [DEFAULT_MODEL_BY_PROVIDER["openrouter"]],
        },
        "openrouter_accepts_free_text_model": True,
    }


def update_ai_config(
    prompt_template=None,
    model_name=None,
    max_processing=None,
    provider=None,
    fallback_provider=None,
    timeout_seconds=None,
) -> Dict[str, Any]:
    if prompt_template is not None:
        app_config_service.set_config("prompt_template", prompt_template)

    # Provedor e modelo sao validados como par: `gemini-2.0-flash` no OpenRouter
    # e `openrouter/auto` no Gemini sao ambos invalidos, e o erro so apareceria
    # na primeira chamada real se validassemos cada um isolado.
    settings = ai_router.resolve_settings()
    novo_provider = (provider or settings["provider"]).strip().lower()
    novo_modelo = model_name if model_name is not None else settings["model"]
    if provider is not None and model_name is None:
        # Trocar so o provedor: adota o modelo default dele, senao herdaria um
        # modelo do provedor anterior que nao existe no novo.
        novo_modelo = DEFAULT_MODEL_BY_PROVIDER.get(novo_provider, novo_modelo)

    if provider is not None or model_name is not None:
        validate_model(novo_provider, novo_modelo)
        app_config_service.set_config("ia_provider", novo_provider)
        app_config_service.set_config("ia_model", novo_modelo)

    if fallback_provider is not None:
        normalizado = str(fallback_provider).strip().lower()
        if normalizado and normalizado not in PROVIDERS:
            raise ValueError(f"Provedor de fallback invalido: {fallback_provider}")
        if normalizado == novo_provider:
            raise ValueError("Fallback nao pode ser igual ao provedor primario")
        app_config_service.set_config("ia_fallback_provider", normalizado)

    if timeout_seconds is not None:
        try:
            app_config_service.set_config("ia_timeout_seconds", max(1, int(timeout_seconds)))
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds invalido") from exc

    if max_processing is not None:
        try:
            validated = max(1, int(max_processing))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_processing invalido") from exc
        app_config_service.set_config("max_processing", validated)

    return get_ai_config()


def run_model(prompt_payload: str, config_overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Executa o prompt no provedor configurado e devolve o JSON extraido.

    O par (provedor, modelo) vem de `configuracoes_aplicacao`; ver
    `nistiprint_shared.services.ai.router`. Esta funcao mantem a assinatura
    antiga por compatibilidade — quem precisa dos metadados da execucao usa
    `run_model_detailed`.
    """
    return run_model_detailed(prompt_payload, config_overrides=config_overrides)[0]


def run_model_detailed(prompt_payload: str, *, config_overrides: Dict[str, Any] | None = None) -> tuple[Dict[str, Any], AIResponse]:
    """Igual a `run_model`, mas devolve tambem a resposta bruta do provedor.

    Os metadados importam para auditoria: com `openrouter/auto` o modelo e
    escolhido do outro lado, entao sem registrar `model_used` nao ha como
    explicar depois por que dois pedidos parecidos sairam diferentes.
    """
    response = ai_router.complete(load_prompt_template(config_overrides), prompt_payload, settings=config_overrides)
    return extract_json(response.text), response


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
        "latest_buyer_message": row.get("latest_buyer_message") or "",
        "items": items,
        "buyer_info": buyer_info,
        "buyer_username": row.get("buyer_username") or buyer_info.get("username") or "",
        "buyer_id": row.get("buyer_user_id") or row.get("contact_marketplace_id") or buyer_info.get("buyer_user_id"),
        "marketplace_integration_id": row.get("marketplace_integration_id"),
        "chat_context_ambiguous": row.get("chat_context_ambiguous", False),
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
    if last_ai_executed_at is None:
        return has_message_to_seller or bool(order.get("has_chat_messages")) or last_buyer_message_at is not None
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
    situacao_ids=None,
    numero_pedido_prefix=None,
):
    query = (
        supabase_db.table("pedidos")
        .select(
            "id,numero_pedido,codigo_pedido_externo,data_venda,informacoes_cliente,"
            "cliente_nome,cliente_documento,cliente_telefone,cliente_email,canal_venda_id,"
            "situacao_pedido_id,buyer_username,marketplace_order_id,message_to_seller,pedido_shopee_id,"
            "shipping_carrier,contact_marketplace_id,buyer_user_id,marketplace_integration_id"
        )
        .in_("canal_venda_id", _get_shopee_channel_ids())
        .in_("situacao_pedido_id", situacao_ids or STATUS_PERSONALIZACAO)
        .order("data_venda", desc=True)
    )

    if order_sn:
        query = query.eq("codigo_pedido_externo", str(order_sn))
    elif pedido_ids:
        query = query.in_("id", pedido_ids)
    elif numero_pedido_prefix is not None:
        prefix = str(numero_pedido_prefix)
        if not prefix.isdigit():
            raise ValueError("O prefixo do número do pedido deve conter apenas dígitos")
        query = query.or_(
            f"numero_pedido.like.{prefix}%,codigo_pedido_externo.like.{prefix}%"
        )

    if limit and not pedido_ids and not order_sn:
        query = query.limit(max(limit * 4, limit, 150))

    return query.execute().data or []


def _fetch_shopee_messages_for_orders(orders: List[Dict[str, Any]]) -> Dict[int, str]:
    """Recupera observacoes que existem no espelho, mas faltam em `pedidos`."""
    missing = [
        order for order in orders
        if not str(order.get("message_to_seller") or "").strip()
    ]
    if not missing:
        return {}

    mirror_rows = []
    mirror_ids = [order.get("pedido_shopee_id") for order in missing if order.get("pedido_shopee_id")]
    order_sns = [str(order.get("codigo_pedido_externo")) for order in missing if order.get("codigo_pedido_externo")]
    columns = "id,codigo_pedido,mensagem,raw_payload"

    if mirror_ids:
        mirror_rows += (
            supabase_db.table("pedidos_shopee")
            .select(columns)
            .in_("id", mirror_ids)
            .execute()
            .data
            or []
        )
    if order_sns:
        mirror_rows += (
            supabase_db.table("pedidos_shopee")
            .select(columns)
            .in_("codigo_pedido", order_sns)
            .execute()
            .data
            or []
        )

    by_id = {str(row.get("id")): row for row in mirror_rows if row.get("id") is not None}
    by_order_sn = {
        str(row.get("codigo_pedido")): row
        for row in mirror_rows
        if row.get("codigo_pedido") not in (None, "")
    }
    messages = {}
    for order in missing:
        mirror = by_id.get(str(order.get("pedido_shopee_id")))
        if mirror is None:
            mirror = by_order_sn.get(str(order.get("codigo_pedido_externo")))
        message = _message_from_shopee_mirror(mirror or {})
        if message:
            messages[order["id"]] = message
    return messages


def _fetch_chat_stats_by_username(usernames: List[str], order_dates: List[Any], buyer_ids: Optional[List[Any]] = None) -> Dict[str, Dict[str, Any]]:
    usernames = [username for username in usernames if username]
    if not usernames:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=CHAT_LOOKBACK_DAYS)

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
        .select("id,from_id,from_user_name,to_user_name,created_at")
        .in_("from_user_name", usernames)
        .gte("created_at", cutoff.isoformat())
        .execute()
        .data
        or []
    )
    consume(from_rows)
    if buyer_ids:
        id_rows = (supabase_db.table("mensagem_chat_shopee").select("id,from_id,from_user_name,to_user_name,created_at").in_("from_id", [str(value) for value in buyer_ids if value not in (None, "")]).gte("created_at", cutoff.isoformat()).execute().data or [])
        id_to_username = {str(value): usernames[index] for index, value in enumerate(buyer_ids) if index < len(usernames) and value not in (None, "")}
        for row in id_rows:
            if not row.get("from_user_name"):
                row["from_user_name"] = id_to_username.get(str(row.get("from_id")))
        consume(id_rows)

    to_rows = (
        supabase_db.table("mensagem_chat_shopee")
        .select("id,from_id,from_user_name,to_user_name,created_at")
        .in_("to_user_name", usernames)
        .gte("created_at", cutoff.isoformat())
        .execute()
        .data
        or []
    )
    consume(to_rows)

    return stats


def _fetch_chat_stats_for_orders(orders: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    if not orders:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=CHAT_LOOKBACK_DAYS)
    buyer_ids = [str(order.get("buyer_user_id") or order.get("contact_marketplace_id")) for order in orders if order.get("buyer_user_id") or order.get("contact_marketplace_id")]
    usernames = [str(order.get("buyer_username")).strip() for order in orders if order.get("buyer_username")]
    columns = (
        "id,installed_integration_id,from_id,from_user_name,to_user_name,"
        "created_at,type,display_content"
    )
    rows = []
    if buyer_ids:
        rows += (supabase_db.table("view_mensagens_chat_ai_v2").select(columns)
                 .in_("from_id", buyer_ids).gte("created_at", cutoff.isoformat()).execute().data or [])
    if usernames:
        rows += (supabase_db.table("view_mensagens_chat_ai_v2").select(columns)
                 .in_("from_user_name", usernames).gte("created_at", cutoff.isoformat()).execute().data or [])
        rows += (supabase_db.table("view_mensagens_chat_ai_v2").select(columns)
                 .in_("to_user_name", usernames).gte("created_at", cutoff.isoformat()).execute().data or [])
    rows = list({str(row.get("id")): row for row in rows}.values())
    stats = {
        order.get("id"): {
            "last_chat_message_at": None,
            "last_buyer_message_at": None,
            "latest_buyer_message": "",
            "has_chat_messages": False,
        }
        for order in orders
    }
    for row in rows:
        created_at = _parse_datetime(row.get("created_at"))
        if not created_at:
            continue
        for order in orders:
            integration = str(order.get("marketplace_integration_id") or "")
            row_integration = str(row.get("installed_integration_id") or "")
            if integration and row_integration and integration != row_integration:
                continue
            buyer_id = str(order.get("buyer_user_id") or order.get("contact_marketplace_id") or "")
            username = str(order.get("buyer_username") or "").strip()
            buyer_match = bool((buyer_id and str(row.get("from_id") or "") == buyer_id) or (username and row.get("from_user_name") == username))
            if not (buyer_match or (username and row.get("to_user_name") == username)):
                continue
            current = stats[order.get("id")]
            current["has_chat_messages"] = True
            if not current["last_chat_message_at"] or created_at > current["last_chat_message_at"]:
                current["last_chat_message_at"] = created_at
            if buyer_match and (not current["last_buyer_message_at"] or created_at > current["last_buyer_message_at"]):
                current["last_buyer_message_at"] = created_at
                display_content = str(row.get("display_content") or "").strip()
                current["latest_buyer_message"] = display_content if row.get("type") == "text" else ""
    return stats

def _assemble_orders(
    order_sn=None,
    pedido_ids=None,
    limit=None,
    recent_days: Optional[int] = None,
    situacao_ids=None,
    numero_pedido_prefix=None,
):
    base_orders = _fetch_recent_personalized_orders(
        order_sn=order_sn,
        pedido_ids=pedido_ids,
        limit=limit,
        recent_days=recent_days,
        situacao_ids=situacao_ids,
        numero_pedido_prefix=numero_pedido_prefix,
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

    shopee_messages_by_order = _fetch_shopee_messages_for_orders(filtered_orders)

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
    latest_successful_logs = {}
    if order_sns:
        log_rows = (
            supabase_db.table("logs_execucao_ia")
            .select("id,order_sn,executed_at,status,extracted_personalization,model_result")
            .in_("order_sn", order_sns)
            .order("executed_at", desc=True)
            .order("id", desc=True)
            .execute()
            .data
            or []
        )
        for log in log_rows:
            key = str(log["order_sn"])
            latest_logs.setdefault(key, log)
            if str(log.get("status") or "").lower() == "success":
                latest_successful_logs.setdefault(key, log)

    usernames = []
    order_dates = []
    for order in filtered_orders:
        contato = _parse_json_if_needed(order.get("informacoes_cliente"), {}) or {}
        buyer_info = {"username": order.get("buyer_username") or contato.get("username") or contato.get("buyer_username")}
        usernames.append(_extract_buyer_username(buyer_info, fallback=order.get("cliente_nome") or contato.get("nome") or ""))
        order_dates.append(order.get("data_venda"))

    chat_stats_by_order = _fetch_chat_stats_for_orders(filtered_orders)

    buyer_order_counts = {}
    for candidate in filtered_orders:
        key = (candidate.get("marketplace_integration_id"), candidate.get("buyer_user_id") or candidate.get("contact_marketplace_id") or candidate.get("buyer_username"))
        if key[1]:
            buyer_order_counts[key] = buyer_order_counts.get(key, 0) + 1

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
        chat_stats = chat_stats_by_order.get(order["id"], {})
        latest_log = latest_logs.get(order_sn_value, {})
        order_items = []

        for item in items_by_order.get(order["id"], []):
            item_personalizations = personalizations_by_item.get(item["id"])
            if item_personalizations is None:
                item_personalizations = personalizations_by_desc.get(
                    (order_sn_value, str(item.get("descricao") or "").strip()),
                    [],
                )
            if not item_personalizations:
                successful_log = latest_successful_logs.get(order_sn_value) or {}
                extracted = _parse_json_if_needed(
                    successful_log.get("extracted_personalization"), []
                )
                if not isinstance(extracted, list):
                    extracted = []
                item_description = str(item.get("descricao") or "").strip()
                item_personalizations = []
                for personalization in extracted:
                    if not isinstance(personalization, dict):
                        continue
                    extracted_description = str(
                        personalization.get("item_description") or ""
                    ).strip()
                    extracted_item_id = str(personalization.get("item_id") or "")
                    if extracted_description != item_description and extracted_item_id != str(item.get("id")):
                        continue
                    if not str(personalization.get("customization_name") or "").strip() and not str(
                        personalization.get("customization_initial") or ""
                    ).strip():
                        continue
                    item_personalizations.append({
                        **personalization,
                        "status": personalization.get("status") or "SUCCESS",
                    })
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
        message_to_seller = (
            str(order.get("message_to_seller") or "").strip()
            or shopee_messages_by_order.get(order["id"], "")
        )
        has_buyer_signal = bool(message_to_seller.strip()) or bool(last_buyer_message_at)
        buyer_key = (
            order.get("marketplace_integration_id"),
            order.get("buyer_user_id") or order.get("contact_marketplace_id") or order.get("buyer_username"),
        )
        chat_context_ambiguous = buyer_order_counts.get(buyer_key, 0) > 1
        latest_buyer_message = "" if chat_context_ambiguous else chat_stats.get("latest_buyer_message", "")

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
            "latest_buyer_message": latest_buyer_message,
            "buyer_username": buyer_username,
            "buyer_id": order.get("buyer_user_id") or order.get("contact_marketplace_id"),
            "marketplace_integration_id": order.get("marketplace_integration_id"),
            "chat_context_ambiguous": chat_context_ambiguous,
            "has_chat_messages": bool(chat_stats.get("has_chat_messages")),
            "last_chat_message_at": chat_stats.get("last_chat_message_at").isoformat() if chat_stats.get("last_chat_message_at") else None,
            "last_buyer_message_at": last_buyer_message_at.isoformat() if last_buyer_message_at else None,
            "last_ai_executed_at": last_ai_executed_at,
            "ai_status": ai_status,
            "has_buyer_message": has_buyer_signal,
            "needs_ai_processing": should_process_order({
                "has_chat_messages": bool(chat_stats.get("has_chat_messages")),
                "last_ai_executed_at": last_ai_executed_at,
                "last_buyer_message_at": last_buyer_message_at.isoformat() if last_buyer_message_at else None,
                "ai_status": ai_status,
                "message_to_seller": message_to_seller,
            }),
            "itens": order_items,
        })

    return assembled


def select_orders_for_processing(order_sn=None, pedido_ids=None, limit=None, force=False, integration_id=None,
                                respect_account_limit=True):
    normalized_limit = None
    if limit not in (None, 0):
        normalized_limit = max(1, int(limit))

    rows = _select_orders_for_processing(
        order_sn=order_sn,
        pedido_ids=pedido_ids,
        limit=normalized_limit,
        integration_id=integration_id,
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
                "marketplace_integration_id": normalized.get("marketplace_integration_id"),
            })
        else:
            skipped.append({
                "id": normalized["id"],
                "order_sn": normalized["shopee_order_sn"],
                "reason": "up_to_date",
            })

    # A tela de configuração guarda o limite por conta conectada. Pedidos
    # legados sem integração identificada mantêm o comportamento anterior.
    if respect_account_limit and not pedido_ids and not order_sn and to_process:
        from nistiprint_shared.services.ai_personalization_account_config import get_config
        limits_by_account = {}
        counts_by_account = {}
        limited = []
        for candidate in to_process:
            integration_id = candidate.get("marketplace_integration_id")
            if not integration_id:
                if not normalized_limit or counts_by_account.get("legacy", 0) < normalized_limit:
                    limited.append(candidate)
                    counts_by_account["legacy"] = counts_by_account.get("legacy", 0) + 1
                continue
            key = str(integration_id)
            if key not in limits_by_account:
                limits_by_account[key] = int(get_config(int(integration_id))["max_processing"])
            account_limit = limits_by_account[key]
            if normalized_limit:
                account_limit = min(account_limit, normalized_limit)
            if counts_by_account.get(key, 0) < account_limit:
                limited.append(candidate)
                counts_by_account[key] = counts_by_account.get(key, 0) + 1
        to_process = limited

    return to_process, skipped


def _select_orders_for_processing(order_sn=None, pedido_ids=None, limit=None, integration_id=None):
    """Carrega apenas sinais de elegibilidade, sem montar detalhes da listagem.

    A montagem completa de pedidos também consulta itens, personalizacoes,
    pedidos Bling e logs para renderizar a pagina. A fila so precisa saber se
    cada pedido tem item personalizado e se recebeu mensagem nova.
    """
    channel_ids = _get_shopee_channel_ids()
    query = (
        supabase_db.table("pedidos")
        .select(
            "id,codigo_pedido_externo,data_venda,pedido_shopee_id,situacao_pedido_id,buyer_username,"
            "message_to_seller,contact_marketplace_id,buyer_user_id,marketplace_integration_id"
        )
        .in_("canal_venda_id", channel_ids)
        .in_("situacao_pedido_id", STATUS_PERSONALIZACAO)
        .order("data_venda", desc=True)
    )

    if integration_id is not None:
        query = query.eq("marketplace_integration_id", int(integration_id))
    if order_sn:
        query = query.eq("codigo_pedido_externo", str(order_sn))
    elif pedido_ids:
        query = query.in_("id", pedido_ids)
    elif limit:
        # Mantem o mesmo conjunto de candidatos usado pela selecao anterior;
        # o limite final e aplicado depois de avaliar quais precisam de IA.
        query = query.limit(max(limit * 4, limit, 150))

    base_orders = []
    offset = 0
    while True:
        page = query.range(offset, offset + SELECTION_PAGE_SIZE - 1).execute().data or []
        base_orders.extend(page)
        if len(page) < SELECTION_PAGE_SIZE:
            break
        offset += SELECTION_PAGE_SIZE

    if not base_orders:
        return []

    order_ids = [row["id"] for row in base_orders]
    personalized_order_ids = set()
    for start in range(0, len(order_ids), SELECTION_ID_CHUNK_SIZE):
        chunk = order_ids[start:start + SELECTION_ID_CHUNK_SIZE]
        items_query = (
            supabase_db.table("itens_pedido")
            .select("pedido_id")
            .in_("pedido_id", chunk)
            .eq("personalizado", True)
        )
        item_offset = 0
        while True:
            items = items_query.range(
                item_offset, item_offset + SELECTION_PAGE_SIZE - 1
            ).execute().data or []
            personalized_order_ids.update(item["pedido_id"] for item in items)
            if len(items) < SELECTION_PAGE_SIZE:
                break
            item_offset += SELECTION_PAGE_SIZE

    orders = [row for row in base_orders if row["id"] in personalized_order_ids]
    if not orders:
        return []

    messages_by_order = _fetch_shopee_messages_for_orders(orders)
    latest_logs = {}
    order_sns = [str(row["codigo_pedido_externo"]) for row in orders if row.get("codigo_pedido_externo")]
    for start in range(0, len(order_sns), SELECTION_ID_CHUNK_SIZE):
        chunk = order_sns[start:start + SELECTION_ID_CHUNK_SIZE]
        logs_query = (
            supabase_db.table("logs_execucao_ia")
            .select("order_sn,executed_at,status")
            .in_("order_sn", chunk)
            .order("executed_at", desc=True)
        )
        log_offset = 0
        while True:
            logs = logs_query.range(
                log_offset, log_offset + SELECTION_PAGE_SIZE - 1
            ).execute().data or []
            for log in logs:
                latest_logs.setdefault(str(log["order_sn"]), log)
            if len(logs) < SELECTION_PAGE_SIZE:
                break
            log_offset += SELECTION_PAGE_SIZE

    chat_stats = _fetch_chat_stats_for_orders(orders)

    selected = []
    for row in orders:
        order_sn_value = str(row.get("codigo_pedido_externo") or "")
        latest_log = latest_logs.get(order_sn_value, {})
        stats = chat_stats.get(row["id"], {})
        selected.append({
            "id": row["id"],
            "marketplace_integration_id": row.get("marketplace_integration_id"),
            "numero_loja": order_sn_value,
            "shopee_message": (
                str(row.get("message_to_seller") or "").strip()
                or messages_by_order.get(row["id"], "")
            ),
            "has_chat_messages": bool(stats.get("has_chat_messages")),
            "last_ai_executed_at": latest_log.get("executed_at"),
            "last_buyer_message_at": (
                stats["last_buyer_message_at"].isoformat()
                if stats.get("last_buyer_message_at") else None
            ),
            "ai_status": latest_log.get("status") or "NOT_PROCESSED",
        })
    return selected


def _pedidos_do_comprador(buyer_id, buyer_username, integration_id) -> List[Dict[str, Any]]:
    """Pedidos Shopee do mesmo comprador dentro da janela de contexto.

    Precisa ser consulta propria. Quando a IA roda para um pedido so -- que e o
    caminho de `_load_order_for_ai` e, portanto, de toda execucao real -- a lista
    montada em memoria tem uma linha, e a ambiguidade justamente do caso perigoso
    (dois pedidos do mesmo comprador disputando a mesma conversa) passaria
    despercebida.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=CHAT_LOOKBACK_DAYS)
    query = (
        supabase_db.table("pedidos")
        .select("id,codigo_pedido_externo,data_venda,marketplace_integration_id")
        .in_("canal_venda_id", _get_shopee_channel_ids())
        .gte("data_venda", cutoff.isoformat())
        .order("data_venda", desc=False)
    )
    if buyer_id not in (None, ""):
        query = query.eq("buyer_user_id", buyer_id)
    elif buyer_username:
        query = query.eq("buyer_username", buyer_username)
    else:
        return []
    try:
        rows = query.execute().data or []
    except Exception as exc:
        logger.warning("Nao foi possivel listar pedidos do comprador: %s", exc)
        return []
    if integration_id:
        rows = [
            row for row in rows
            if not row.get("marketplace_integration_id")
            or str(row.get("marketplace_integration_id")) == str(integration_id)
        ]
    return rows


def _ancora_do_pedido(order_sn: str, buyer_id, buyer_username) -> Optional[datetime]:
    """Momento em que o comprador anexou este pedido na conversa.

    A Shopee manda uma mensagem `order` quando o comprador abre o chat a partir
    de um pedido. E a unica marcacao explicita de "daqui para baixo e sobre este
    pedido", e vale mais que qualquer corte por tempo.
    """
    if not order_sn:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=CHAT_LOOKBACK_DAYS)
    try:
        query = (
            supabase_db.table("mensagem_chat_shopee")
            .select("created_at,from_id,from_user_name")
            .eq("type", "order")
            .eq("content->>order_sn", str(order_sn))
            .gte("created_at", cutoff.isoformat())
            .order("created_at", desc=False)
            .limit(1)
        )
        rows = query.execute().data or []
    except Exception as exc:
        logger.warning("Nao foi possivel buscar ancora de pedido no chat: %s", exc)
        return None
    if not rows:
        return None
    return _parse_datetime(rows[0].get("created_at"))


def _janela_do_pedido(order: Dict[str, Any]) -> Dict[str, Any]:
    """Recorte da conversa que pertence a este pedido.

    A conversa da Shopee e por comprador, nunca por pedido -- em producao sao 993
    conversas para 993 compradores. Com mais de um pedido do mesmo comprador na
    janela, o unico criterio disponivel e o tempo: o que vem depois do pedido
    seguinte ja e assunto do pedido seguinte.
    """
    buyer_id = order.get("buyer_id")
    buyer_username = order.get("buyer_username") or ""
    irmaos = _pedidos_do_comprador(buyer_id, buyer_username, order.get("marketplace_integration_id"))
    data_pedido = _parse_datetime(order.get("order_date"))

    posteriores = []
    for row in irmaos:
        if str(row.get("codigo_pedido_externo") or "") == str(order.get("shopee_order_sn") or ""):
            continue
        data_irmao = _parse_datetime(row.get("data_venda"))
        if data_pedido and data_irmao and data_irmao > data_pedido:
            posteriores.append(data_irmao)

    ancora = _ancora_do_pedido(order.get("shopee_order_sn"), buyer_id, buyer_username)
    return {
        "ambiguo": len(irmaos) > 1,
        "total_pedidos_comprador": len(irmaos),
        "limite_superior": min(posteriores) if posteriores else None,
        "ancora": ancora,
    }


def _fetch_chat_messages(buyer_username: str, buyer_id=None, integration_id=None, order_date=None,
                         last_ai_executed_at=None, limite_superior=None, ancora=None,
                         conversation_id=None) -> List[Dict[str, Any]]:
    if not buyer_username and not buyer_id and not conversation_id:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=CHAT_LOOKBACK_DAYS)

    def query(field, value):
        request = (supabase_db.table("view_mensagens_chat_ai_v2").select("*")
                   .eq(field, value).gte("created_at", cutoff.isoformat())
                   .order("created_at", desc=True).limit(CHAT_CONTEXT_LIMIT))
        return request.execute().data or []

    rows = []
    # A conversa e a chave certa quando conhecida. A API do SellerChat devolve as
    # mensagens sem `from_user_name`/`to_user_name` -- so os ids numericos -- e a
    # busca por username deixaria de fora exatamente as respostas da loja, que so
    # chegam por ela. Os filtros por comprador ficam como fallback para as linhas
    # antigas, vindas de webhook, cuja conversa pode nao estar registrada.
    if conversation_id not in (None, ""):
        rows += query("conversation_id", conversation_id)
    if buyer_id not in (None, ""):
        rows += query("from_id", buyer_id)
    if buyer_username:
        # Keeps legacy rows without numeric identity and preserves the proven
        # seven-day username fallback instead of globally truncating at 5,000.
        rows += query("from_user_name", buyer_username)
        rows += query("to_user_name", buyer_username)
    rows = list({str(row.get("id")): row for row in rows}.values())
    rows = [row for row in rows if (not integration_id or not row.get("installed_integration_id")
            or str(row.get("installed_integration_id")) == str(integration_id))]
    rows.sort(key=lambda row: _parse_datetime(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))

    # A ancora, quando existe, e uma marcacao do proprio comprador de onde o
    # assunto deste pedido comeca; o limite superior e o pedido seguinte dele.
    if ancora is not None:
        rows = [row for row in rows
                if (_parse_datetime(row.get("created_at")) or ancora) >= ancora]
    if limite_superior is not None:
        rows = [row for row in rows
                if (_parse_datetime(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
                < limite_superior]

    return compact_chat_messages(rows[-CHAT_CONTEXT_LIMIT:], buyer_username, buyer_id=buyer_id)


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


def compact_chat_messages(messages: List[Dict[str, Any]], buyer_username: str, buyer_id=None) -> List[Dict[str, Any]]:
    compacted = []
    for row in messages:
        display_content = (row.get("display_content") or "").strip()
        if not display_content:
            continue
        row_from_id = row.get("from_id")
        if buyer_id not in (None, "") and row_from_id not in (None, ""):
            is_buyer = str(row_from_id) == str(buyer_id)
        else:
            is_buyer = bool(buyer_username and row.get("from_user_name") == buyer_username)
        sender_role = "Comprador" if is_buyer else "Vendedor"
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


def _estado_da_conversa(buyer_id, integration_id) -> Optional[Dict[str, Any]]:
    if buyer_id in (None, ""):
        return None
    try:
        rows = (
            supabase_db.table("conversas_chat_shopee")
            .select("conversation_id,installed_integration_id,status_completude,"
                    "ids_nao_recuperados,ultima_mensagem_em,mensagens_esperadas,"
                    "mensagens_presentes")
            .eq("buyer_user_id", buyer_id)
            .order("ultima_mensagem_em", desc=True)
            .limit(5)
            .execute().data or []
        )
    except Exception as exc:
        logger.warning("Nao foi possivel ler o estado da conversa: %s", exc)
        return None
    if integration_id:
        da_integracao = [
            row for row in rows
            if not row.get("installed_integration_id")
            or str(row.get("installed_integration_id")) == str(integration_id)
        ]
        rows = da_integracao or rows
    return rows[0] if rows else None


def _tentar_fechar_conversa(estado: Dict[str, Any]) -> Dict[str, Any]:
    """Uma tentativa curta de completar a conversa, sem paginar.

    So vale a pena quando ja se sabe quais IDs faltam: e uma chamada. Quando nao
    se sabe -- resposta da loja ainda nao espelhada --, pedir a varredura e adiar
    o pedido custa menos que segurar a IA numa paginacao de historico.
    """
    from nistiprint_shared.services.shopee_chat_service import shopee_chat_ingest_service

    conversation_id = estado.get("conversation_id")
    integration = shopee_chat_ingest_service.carregar_integracao(
        estado.get("installed_integration_id")
    )
    if not integration or conversation_id in (None, ""):
        return estado

    ausentes = estado.get("ids_nao_recuperados") or []
    if not ausentes:
        shopee_chat_ingest_service.solicitar_sincronizacao(
            conversation_id, integration_id=estado.get("installed_integration_id")
        )
        return estado

    resultado = shopee_chat_ingest_service.resolver_bundle(
        integration, conversation_id, ausentes,
        timeout_seconds=CHAT_GATE_TIMEOUT_SEGUNDOS,
    )
    if resultado.get("status") != "success":
        return estado
    return {
        **estado,
        "status_completude": resultado.get("status_completude") or estado.get("status_completude"),
        "ids_nao_recuperados": resultado.get("ids_nao_recuperados") or [],
    }


def avaliar_contexto_de_chat(order: Dict[str, Any]) -> Dict[str, Any]:
    """Decide se da para confiar na conversa deste pedido.

    Existe porque ate aqui a IA nao tinha como saber que faltava conteudo: o
    `bundle_message` era filtrado da view e o silencio parecia ausencia de
    mensagem. Em 76% das execucoes medidas a conversa estava incompleta.

    No regime normal isto nao custa nada: o bundle e resolvido no ingest, segundos
    depois do push, e a conversa ja chega aqui completa.
    """
    if not CHAT_GATE_ATIVO:
        return {"acao": "seguir", "status_completude": "gate_desligado"}

    estado = _estado_da_conversa(order.get("buyer_id"), order.get("marketplace_integration_id"))
    if not estado:
        # Sem conversa registrada nao ha lacuna conhecida: o pedido pode ter
        # apenas `message_to_seller`, que nao passa pelo SellerChat.
        return {"acao": "seguir", "status_completude": "sem_conversa"}

    status = str(estado.get("status_completude") or "")
    if status in ("pendente", "erro"):
        estado = _tentar_fechar_conversa(estado)
        status = str(estado.get("status_completude") or "")

    ausentes = estado.get("ids_nao_recuperados") or []
    base = {
        "conversation_id": estado.get("conversation_id"),
        "status_completude": status,
        "mensagens_nao_recuperadas": len(ausentes),
    }
    if status == "completa":
        return {**base, "acao": "seguir"}
    if status == "expirada":
        # A Shopee ja ocultou o que faltava; esperar mais nao traz de volta.
        # Roda, mas o resultado nasce para revisao humana.
        return {**base, "acao": "seguir", "revisar": True}
    return {**base, "acao": "adiar"}


def _load_order_for_ai(pedido_id: int) -> Dict[str, Any]:
    rows = _assemble_orders(pedido_ids=[pedido_id], recent_days=None)
    if not rows:
        raise ValueError(f"Pedido {pedido_id} nao encontrado na view de personalizados")

    normalized = _normalize_order_row(rows[0])

    # O gate vem antes da leitura das mensagens: quando ele consegue fechar a
    # conversa, o que faltava ja esta gravado quando o contexto e montado.
    normalized["chat_gate"] = (
        avaliar_contexto_de_chat(normalized)
        if should_process_order(normalized)
        else {"acao": "seguir", "status_completude": "nao_avaliado"}
    )

    janela = _janela_do_pedido(normalized)
    normalized["chat_context_ambiguous"] = bool(
        normalized.get("chat_context_ambiguous")
    ) or bool(janela.get("ambiguo"))
    normalized["chat_janela"] = {
        "total_pedidos_comprador": janela.get("total_pedidos_comprador"),
        "limite_superior": janela["limite_superior"].isoformat() if janela.get("limite_superior") else None,
        "ancora": janela["ancora"].isoformat() if janela.get("ancora") else None,
    }
    normalized["chat_messages"] = _fetch_chat_messages(
        buyer_username=normalized.get("buyer_username", ""),
        buyer_id=normalized.get("buyer_id"),
        integration_id=normalized.get("marketplace_integration_id"),
        order_date=normalized.get("order_date"),
        last_ai_executed_at=normalized.get("last_ai_executed_at"),
        limite_superior=janela.get("limite_superior"),
        ancora=janela.get("ancora"),
        conversation_id=(normalized.get("chat_gate") or {}).get("conversation_id"),
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


def _registros_personalizacao(order: Dict[str, Any], result: Dict[str, Any], *, model_name: str | None = None):
    shopee_order_sn = str(order["shopee_order_sn"])
    items_by_id = {str(item.get("id")): item for item in (order.get("items") or [])}
    now_iso = datetime.now(timezone.utc).isoformat()

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
                "source": model_name or get_model_name(),
                "processed_at": now_iso,
                "quantity_to_personalize": details["quantity_to_personalize"],
                "initial_source_message_id": details["initial_source_message_id"],
            },
            "updated_at": now_iso,
        })

    return shopee_order_sn, records


def _persistir_personalizacao(
    order: Dict[str, Any], result: Dict[str, Any], *,
    model_name: str | None = None, log_record: Dict[str, Any],
):
    shopee_order_sn, records = _registros_personalizacao(order, result, model_name=model_name)
    supabase_db.rpc("persist_shopee_personalization_result", {
        "p_shopee_order_sn": shopee_order_sn,
        "p_personalizations": records,
        "p_log": log_record,
    }).execute()


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


def _process_single_order_sync(pedido_id: int, force: bool = False, *,
                               execution_context: dict | None = None,
                               persist_result: bool = True):
    order_sn = str(pedido_id)
    prompt_payload = ""
    chat_context = []
    order = _load_order_for_ai(pedido_id)
    order_sn = order["shopee_order_sn"]

    if not should_process_order(order, force=force):
        return {
            "success": True,
            "status": "up_to_date",
            "order_sn": order_sn,
            "message": "Pedido ja esta atualizado para IA.",
        }

    gate = order.get("chat_gate") or {}
    if gate.get("acao") == "adiar":
        # Sem log em `logs_execucao_ia`: registrar aqui marcaria o pedido como
        # processado e ele so voltaria a fila se o comprador escrevesse de novo.
        # O adiamento fica em `execucoes_ai_item`, que e o log do lote.
        return {
            "success": True,
            "status": "chat_incompleto",
            "order_sn": order_sn,
            "message": (
                f"Conversa {gate.get('conversation_id')} incompleta "
                f"({gate.get('mensagens_nao_recuperadas')} mensagens ausentes). "
                "Aguardando a reconciliacao do SellerChat."
            ),
            "chat_gate": gate,
        }

    prompt_payload = generate_prompt_payload(order)
    chat_context = order.get("chat_messages") or []

    try:
        account_overrides = None
        integration_id = order.get("marketplace_integration_id")
        if execution_context is not None:
            account_overrides = execution_context.get("overrides")
        elif integration_id:
            from nistiprint_shared.services.ai_personalization_account_config import shopee_overrides
            account_overrides = shopee_overrides(int(integration_id))
        if execution_context is not None:
            ai_response = ai_router.complete(
                execution_context.get("prompt_template") or load_prompt_template(account_overrides), prompt_payload,
                settings=execution_context["settings"],
                provider_cache=execution_context["providers"],
                provider_registry=execution_context["provider_registry"],
            )
            result = extract_json(ai_response.text)
        else:
            result, ai_response = run_model_detailed(prompt_payload, config_overrides=account_overrides)
        if order.get("chat_context_ambiguous"):
            result["status"] = "NEEDS_REVIEW"
            result["reasoning"] = (
                "Mais de um pedido em andamento compartilha a identidade do comprador; "
                "o contexto de sete dias requer revisao. " + str(result.get("reasoning") or "")
            ).strip()
        if gate.get("revisar"):
            # Perda declarada, nao suposta: a Shopee ocultou as mensagens antes de
            # conseguirmos busca-las. Um NO_PERSONALIZATION_FOUND aqui seria uma
            # conclusao sobre um texto que ninguem leu.
            result["status"] = "NEEDS_REVIEW"
            result["reasoning"] = (
                f"{gate.get('mensagens_nao_recuperadas')} mensagem(ns) do comprador nao "
                "puderam ser recuperadas da Shopee (ocultadas apos 12h sem leitura); "
                "a decisao foi tomada sobre contexto incompleto. "
                + str(result.get("reasoning") or "")
            ).strip()
        model_used = ai_response.model_used or (account_overrides or {}).get("ia_model")
        # Provedor e modelo efetivo ficam no log: com `openrouter/auto` quem
        # escolhe o modelo e o OpenRouter, e sem isso nao ha como auditar
        # depois qual modelo produziu determinado nome.
        log_record = {
            "order_sn": order_sn,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "input_data": _truncate(prompt_payload, 25000),
            "chat_context": _truncate_json(chat_context, 12000),
            "extracted_personalization": _truncate_json(result.get("personalized_items"), 12000),
            "model_result": _truncate_json(result, 15000),
            "status": "success",
            "error_message": None,
            "metadata": {
                **ai_response.to_metadata(),
                "chat_gate": gate,
                "chat_janela": order.get("chat_janela"),
            },
        }
        if persist_result:
            _persistir_personalizacao(
                order, result, model_name=model_used, log_record=log_record
            )
        response = {
            "success": True,
            "status": "success",
            "order_sn": order_sn,
            "message": "Pedido processado com sucesso.",
            "result": result,
        }
        if not persist_result:
            response.update(
                order=order, personalization_records=_registros_personalizacao(
                    order, result, model_name=model_used)[1],
                log_record=log_record,
            )
        return response
    except httpx.PoolTimeout:
        raise
    except Exception as exc:
        logger.error("Erro ao processar pedido %s: %s", pedido_id, exc, exc_info=True)
        if persist_result:
            log_ai_execution(order_sn, prompt_payload, chat_context, "error", error_message=str(exc))
        response = {
            "success": False,
            "status": "error",
            "order_sn": order_sn,
            "message": str(exc),
        }
        if not persist_result:
            response["log_record"] = {
                "order_sn": order_sn, "executed_at": datetime.now(timezone.utc).isoformat(),
                "input_data": _truncate(prompt_payload, 25000),
                "chat_context": _truncate_json(chat_context, 12000),
                "extracted_personalization": None, "model_result": None,
                "status": "error", "error_message": _truncate(str(exc), 1000),
                "metadata": {"model_name": (execution_context or {}).get("settings", {}).get("model")
                             or get_model_name()},
            }
        return response


def create_processing_batch(pedido_ids: List[int], skipped=None, iniciado_por=None,
                            force: bool = False, dispatch: bool = True,
                            source: str = "manual"):
    candidate_rows = pedido_ids
    pedido_ids = [row["id"] if isinstance(row, dict) else int(row)
                  for row in candidate_rows]
    batch_data = {
        "pedido_ids": pedido_ids,
        "total": len(pedido_ids),
        "status": "PENDENTE",
    }
    if iniciado_por is not None:
        batch_data["iniciado_por"] = str(iniciado_por)
    batch_data["force"] = bool(force)
    batch_data["source"] = source
    batch_res = supabase_db.table("execucoes_ai_batch").insert(batch_data).execute()
    if not batch_res.data:
        raise RuntimeError("Falha ao criar batch de IA")

    batch_id = batch_res.data[0]["id"]
    # O insert acima E o enfileiramento: a partir daqui o trabalho existe e
    # esta registrado, e o Postgres e a unica fonte da verdade sobre ele.
    # A mensagem no broker e so a campainha que avisa o worker mais cedo.
    # Por isso ela e best-effort: se o Redis nao atender, o lote continua
    # PENDENTE e `recolher_lotes_ia_parados` o retoma na proxima varredura.
    # Falha de fila passa a atrasar o trabalho, nunca a perde-lo.
    grouped = {}
    for candidate in candidate_rows:
        pedido_id = candidate["id"] if isinstance(candidate, dict) else candidate
        integration_id = candidate.get("marketplace_integration_id") if isinstance(candidate, dict) else None
        account_key = str(integration_id) if integration_id else "legacy"
        grouped.setdefault(account_key, []).append(int(pedido_id))
    if grouped:
        try:
            groups = [{"batch_id": batch_id, "account_key": key,
                       "marketplace_integration_id": int(key) if key != "legacy" else None,
                       "pedido_ids": ids, "force": bool(force), "source": source,
                       "status": "PENDENTE"}
                      for key, ids in grouped.items()]
            supabase_db.table("execucoes_ai_batch_conta").insert(groups).execute()
            work = [{"batch_id": batch_id, "account_key": key, "pedido_id": pedido_id,
                     "status": "PENDENTE", "force": bool(force)}
                    for key, ids in grouped.items() for pedido_id in ids]
            for start in range(0, len(work), 500):
                supabase_db.table("execucoes_ai_batch_pedido").insert(work[start:start + 500]).execute()
        except Exception:
            supabase_db.table("execucoes_ai_batch").delete().eq("id", batch_id).execute()
            raise
    batch_ids = []
    attached_ids = []
    if source == "manual" and grouped:
        for account_key in grouped:
            active = (supabase_db.table("execucoes_ai_batch_conta")
                      .select("batch_id")
                      .eq("account_key", account_key).eq("status", "RODANDO")
                      .limit(1).execute().data or [])
            if not active:
                continue
            active_id = str(active[0]["batch_id"])
            merged = supabase_db.rpc("ai_merge_manual_account_orders", {
                "p_account_key": account_key,
                "p_active_batch_id": active_id,
                "p_new_batch_id": str(batch_id),
            }).execute().data
            result = merged[0] if isinstance(merged, list) and merged else merged
            if result and result.get("merged"):
                attached_ids.append(active_id)
                if iniciado_por is not None:
                    supabase_db.table("execucoes_ai_batch_subscribers").upsert({
                        "batch_id": active_id, "user_id": int(iniciado_por),
                    }, on_conflict="batch_id,user_id").execute()
    remaining_rows = (supabase_db.table("execucoes_ai_batch").select("id,iniciado_por,total,status,criado_em")
                      .eq("id", str(batch_id)).limit(1).execute().data or [])
    remaining = remaining_rows[0] if remaining_rows else None
    batch_ids.extend(dict.fromkeys(attached_ids))
    if remaining:
        batch_ids.append(str(batch_id))
    if not batch_ids:
        batch_ids = [str(batch_id)]
    if remaining and iniciado_por is not None:
        try:
            from nistiprint_shared.services.async_operation_service import async_operation_service
            async_operation_service.sync_ai_batch(remaining)
        except Exception:
            logger.exception("Não foi possível registrar o lote de IA na central de atividade: %s", batch_id)
    for attached_id in dict.fromkeys(attached_ids):
        _sync_ai_batch_progress(attached_id)
    enfileirado = _tocar_campainha_do_batch(str(batch_id)) if dispatch and remaining else False

    return {
        "batch_id": str(batch_id) if remaining else batch_ids[0],
        "batch_ids": batch_ids,
        "total": len(pedido_ids),
        "skipped": skipped or [],
        "enfileirado": enfileirado,
        "execution_state": ("starting" if remaining else ("attached" if attached_ids else "empty")),
        "execution_batch_id": str(batch_id) if remaining else None,
    }


def _tocar_campainha_do_batch(batch_id: str) -> bool:
    """Publica o aviso do lote no broker. Retorna False se o broker nao atender.

    Nunca levanta: um broker fora do ar nao invalida o lote, so adia o inicio.
    Quem precisa saber a diferenca le o retorno.
    """
    try:
        processar_batch_ia.delay(batch_id)
        return True
    except Exception as exc:
        logger.warning(
            "Broker nao aceitou o aviso do batch %s (%s). O lote fica PENDENTE "
            "e sera retomado pela varredura periodica.",
            batch_id, exc,
        )
        return False


@shared_task(name="services.ai_personalization.processar_batch", bind=True)
def processar_batch_ia(self, batch_id: str, direct: bool = False):
    batch = supabase_db.table("execucoes_ai_batch").select("*").eq("id", batch_id).single().execute().data
    if not batch:
        return
    if batch.get("status") in {"CONCLUIDO", "ERRO"}:
        return

    if batch.get("status") == "PENDENTE":
        supabase_db.table("execucoes_ai_batch").update({"status": "RODANDO"}).eq(
            "id", batch_id).eq("status", "PENDENTE").execute()
    batch["status"] = "RODANDO"
    try:
        from nistiprint_shared.services.async_operation_service import async_operation_service
        async_operation_service.sync_ai_batch(batch)
    except Exception:
        logger.exception("Não foi possível atualizar o acompanhamento do lote de IA %s", batch_id)

    groups = (supabase_db.table("execucoes_ai_batch_conta").select("account_key")
              .eq("batch_id", str(batch_id)).eq("status", "PENDENTE").execute().data or [])
    for group in groups:
        if direct:
            processar_conta_ia.run(str(batch_id), group["account_key"], direct=True)
        else:
            processar_conta_ia.apply_async(
                args=[str(batch_id), group["account_key"]], queue="ai_personalization",
            )


@shared_task(name="services.ai_personalization.processar_conta", bind=True,
             acks_late=True, reject_on_worker_lost=True,
             max_retries=None, soft_time_limit=7200, time_limit=7500)
def processar_conta_ia(self, batch_id: str, account_key: str, direct: bool = False):
    """Process up to ten orders while holding the durable account lease."""
    token = str(__import__("uuid").uuid4())
    claimed = (supabase_db.rpc("reivindicar_lote_ai_conta", {
        "p_batch_id": str(batch_id), "p_account_key": str(account_key),
        "p_run_token": token,
    }).execute().data)
    if not claimed:
        group = (supabase_db.table("execucoes_ai_batch_conta").select("status")
                 .eq("batch_id", str(batch_id)).eq("account_key", str(account_key))
                 .limit(1).execute().data or [])
        if not group or group[0].get("status") in {"CONCLUIDO", "ERRO"}:
            return {"status": "completed", "batch_id": batch_id, "account_key": account_key}
        if direct:
            return {"status": "attached", "batch_id": batch_id, "account_key": account_key}
        raise self.retry(countdown=30, max_retries=None)

    run = claimed[0] if isinstance(claimed, list) else claimed
    pedido_ids = [int(value) for value in (run.get("pedido_ids") or [])]
    force = bool(run.get("force"))
    integration_id = run.get("marketplace_integration_id")
    settings = None
    overrides = None
    if integration_id:
        from nistiprint_shared.services.ai_personalization_account_config import shopee_overrides
        overrides = shopee_overrides(int(integration_id))
    prompt_template = load_prompt_template(overrides)
    overrides = {**(overrides or {}), "prompt_template": prompt_template}
    settings = ai_router.resolve_settings(overrides)
    execution_context = {"settings": settings, "overrides": overrides,
                         "prompt_template": prompt_template,
                         "providers": threading.local(), "provider_registry": []}
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_renew_shopee_ai_account_lease,
        args=(str(batch_id), str(account_key), token, stop), daemon=True,
    )
    heartbeat.start()

    def next_pending_order():
        rows = (supabase_db.table("execucoes_ai_batch_pedido").select("pedido_id")
                .eq("batch_id", str(batch_id)).eq("account_key", str(account_key))
                .eq("status", "PENDENTE")
                .lte("available_at", datetime.now(timezone.utc).isoformat())
                .order("pedido_id").limit(1).execute().data or [])
        return int(rows[0]["pedido_id"]) if rows else None

    try:
        for pedido_id, failure in _iter_shopee_ai_pool(
            next_pending_order,
            lambda current_id: _run_shopee_ai_item(
                str(batch_id), str(account_key), token, current_id, force,
                execution_context,
            ),
        ):
            if failure:
                logger.error("Falha ao finalizar pedido IA batch=%s pedido=%s: %s",
                             batch_id, pedido_id, failure)
            _sync_ai_batch_progress(str(batch_id))
    finally:
        stop.set()
        heartbeat.join(timeout=2)
        for provider in execution_context["provider_registry"]:
            close = getattr(provider, "close", None)
            if close:
                close()
    supabase_db.rpc("finalizar_lote_ai_conta", {
        "p_batch_id": str(batch_id), "p_account_key": str(account_key),
        "p_run_token": token,
    }).execute()
    next_group = (supabase_db.table("execucoes_ai_batch_conta").select("batch_id,account_key")
                  .eq("account_key", str(account_key)).eq("status", "PENDENTE")
                  .lte("available_at", datetime.now(timezone.utc).isoformat())
                  .order("source").order("available_at").limit(1).execute().data or [])
    if next_group:
        next_batch_id = str(next_group[0]["batch_id"])
        if direct:
            processar_conta_ia.run(next_batch_id, str(account_key), direct=True)
        else:
            processar_conta_ia.apply_async(
                args=[next_batch_id, str(account_key)], queue="ai_personalization",
            )
    return {"status": "completed", "batch_id": batch_id, "account_key": account_key}


def _iter_shopee_ai_pool(items, process_item, max_workers=10):
    """Yield each completed item and keep no more than max_workers in flight."""
    iterator = iter(items) if not callable(items) else None
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="shopee-ai") as pool:
        futures = {}

        def submit_next():
            if iterator is None:
                item = items()
                if item is None:
                    return False
            else:
                try:
                    item = next(iterator)
                except StopIteration:
                    return False
            futures[pool.submit(process_item, item)] = item
            return True

        for _ in range(max_workers):
            if not submit_next():
                break
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                item = futures.pop(future)
                try:
                    future.result()
                    yield item, None
                except Exception as exc:
                    yield item, exc
                submit_next()


def _sync_ai_batch_progress(batch_id: str):
    try:
        batch = (supabase_db.table("execucoes_ai_batch")
                 .select("id,iniciado_por,pedido_ids,total,processados,sucesso,falha,status,criado_em,finalizado_em")
                 .eq("id", batch_id).maybe_single().execute().data)
        if batch:
            from nistiprint_shared.services.async_operation_service import async_operation_service
            if batch.get("iniciado_por"):
                async_operation_service.sync_ai_batch(batch)
            subscribers = (supabase_db.table("execucoes_ai_batch_subscribers")
                           .select("user_id").eq("batch_id", str(batch_id)).execute().data or [])
            for subscriber in subscribers:
                async_operation_service.sync_ai_batch(
                    batch, owner_user_id=subscriber["user_id"], subscription=True,
                )
    except Exception:
        logger.exception("Não foi possível publicar progresso do lote IA %s", batch_id)


def _renew_shopee_ai_account_lease(batch_id: str, account_key: str,
                                   token: str, stop: threading.Event):
    while not stop.wait(30):
        try:
            supabase_db.rpc("renovar_lote_ai_conta", {
                "p_batch_id": batch_id, "p_account_key": account_key,
                "p_run_token": token,
            }).execute()
        except Exception:
            logger.exception("Falha ao renovar lease IA batch=%s conta=%s", batch_id, account_key)


def _run_shopee_ai_item(batch_id: str, account_key: str, run_token: str,
                        pedido_id: int, force: bool, execution_context: dict):
    started = time.monotonic()
    claim = supabase_db.rpc("reivindicar_item_ai", {
        "p_batch_id": batch_id, "p_account_key": account_key,
        "p_pedido_id": pedido_id, "p_run_token": run_token,
    }).execute().data
    if not claim:
        return
    claimed_item = claim[0] if isinstance(claim, list) else claim
    force = bool(claimed_item.get("force", force))
    attempt = claimed_item.get("attempts", 1)
    failure_message = None
    try:
        result = _process_single_order_sync(
            pedido_id, force=force, execution_context=execution_context,
            persist_result=False,
        )
    except httpx.PoolTimeout as exc:
        if attempt <= 2:
            supabase_db.rpc("adiar_item_ai", {
                "p_batch_id": batch_id, "p_account_key": account_key,
                "p_pedido_id": pedido_id, "p_run_token": run_token,
                "p_error": str(exc)[:500], "p_delay_seconds": 30,
            }).execute()
            return
        failure_message = str(exc)
        result = None
    except Exception as exc:
        logger.exception("Erro ao preparar pedido IA %s", pedido_id)
        failure_message = str(exc)
        result = None
    if result is None:
        error = failure_message or "Falha ao executar o processamento de IA."
        result = {"success": False, "status": "error", "message": error,
                  "log_record": {"order_sn": str(pedido_id),
                                 "executed_at": datetime.now(timezone.utc).isoformat(),
                                 "status": "error", "error_message": error[:1000],
                                 "metadata": {"model_name": execution_context["settings"]["model"]}}}
    if result["status"] == "chat_incompleto":
        status = "ADIADO"
    elif result["status"] == "up_to_date":
        status = "UP_TO_DATE"
    elif result["success"]:
        status = "OK"
    else:
        status = "ERRO"
    order = result.get("order") or {}
    log_record = result.get("log_record")
    supabase_db.rpc("concluir_item_ai", {
        "p_batch_id": batch_id, "p_account_key": account_key,
        "p_pedido_id": pedido_id, "p_run_token": run_token,
        "p_status": status, "p_error": _truncate(result.get("message"), 500),
        "p_duration_ms": int((time.monotonic() - started) * 1000),
        "p_shopee_order_sn": str(order.get("shopee_order_sn") or ""),
        "p_personalizations": result.get("personalization_records") or [],
            "p_log": log_record,
    }).execute()


@shared_task(name="services.ai_personalization.processar_pedido", bind=True, max_retries=2)
def processar_pedido_ia(self, batch_id: str, pedido_id: int):
    # Compatibility shim for messages already in Redis during rollout.
    row = (supabase_db.table("execucoes_ai_batch_pedido").select("account_key")
           .eq("batch_id", batch_id).eq("pedido_id", int(pedido_id)).limit(1).execute().data or [])
    if row:
        return processar_conta_ia.apply_async(args=[batch_id, row[0]["account_key"]],
                                             queue="ai_personalization")


#: Um lote que nasceu ha menos que isso ainda pode estar a caminho do worker;
#: varrer antes disso e correr contra a propria fila.
LOTE_PENDENTE_TOLERANCIA_SEGUNDOS = 120

#: Um lote em RODANDO com progresso parado por mais tempo que isso perdeu
#: mensagens (worker morto no meio do fan-out). Generoso de proposito: cada
#: pedido e uma chamada de IA, e um lote grande demora.
LOTE_RODANDO_TOLERANCIA_SEGUNDOS = 7200


@shared_task(name="services.ai_personalization.recolher_lotes_parados", bind=True)
def recolher_lotes_ia_parados(self):
    """Retoma lotes que ficaram sem campainha e encerra os que se perderam.

    Existe porque o registro do lote e o aviso ao worker sao duas escritas em
    sistemas diferentes, sem transacao entre elas. Sempre que isso acontece
    alguem tem que reconciliar depois — esta task e esse alguem.

    Dois casos, tratados de formas diferentes de proposito:

    PENDENTE parado
        A campainha nao tocou (broker fora do ar, processo morto entre o insert
        e o publish). O trabalho nao comecou, entao e seguro tocar de novo. A
        reivindicacao e um UPDATE condicional: quem conseguir mudar PENDENTE
        para RODANDO ganha o lote, e duas varreduras simultaneas nao disparam o
        mesmo fan-out duas vezes.

    RODANDO parado
        Aqui parte do fan-out pode ter rodado. Reenfileirar duplicaria itens em
        `execucoes_ai_item` e contaria o mesmo pedido duas vezes nos totais, o
        que corromperia o historico para consertar um travamento. Entao so
        marcamos ERRO: a tabela volta a dizer a verdade, e o proximo ciclo
        normal reprocessa o que ficou faltando — `should_process_order` ja
        garante que so o pendente de verdade volta para a IA.
    """
    agora = datetime.now(timezone.utc)
    retomados, encerrados = [], []

    due_groups = (supabase_db.table("execucoes_ai_batch_conta")
                  .select("batch_id,account_key")
                  .eq("status", "PENDENTE")
                  .lt("available_at", agora.isoformat()).limit(500).execute().data or [])
    due_groups.extend(
        supabase_db.table("execucoes_ai_batch_conta")
        .select("batch_id,account_key").eq("status", "RODANDO")
        .lt("lease_until", agora.isoformat()).limit(500).execute().data or []
    )
    for group in due_groups:
        try:
            processar_conta_ia.apply_async(
                args=[group["batch_id"], group["account_key"]],
                queue="ai_personalization",
            )
            retomados.append(f"{group['batch_id']}:{group['account_key']}")
        except Exception:
            logger.exception("Falha ao reenfileirar grupo IA %s/%s",
                             group["batch_id"], group["account_key"])

    limite_pendente = (agora - timedelta(seconds=LOTE_PENDENTE_TOLERANCIA_SEGUNDOS)).isoformat()
    pendentes = (
        supabase_db.table("execucoes_ai_batch")
        .select("id,total,criado_em,iniciado_por,processados,sucesso,falha,status,finalizado_em")
        .eq("status", "PENDENTE")
        .lt("criado_em", limite_pendente)
        .execute()
        .data
        or []
    )

    for lote in pendentes:
        batch_id = lote["id"]
        has_account_groups = (supabase_db.table("execucoes_ai_batch_conta")
                              .select("batch_id").eq("batch_id", batch_id)
                              .limit(1).execute().data or [])
        if has_account_groups:
            continue
        reivindicado = (
            supabase_db.table("execucoes_ai_batch")
            .update({"status": "RODANDO"})
            .eq("id", batch_id)
            .eq("status", "PENDENTE")
            .execute()
            .data
        )
        if not reivindicado:
            # Outra varredura (ou o proprio worker) chegou primeiro.
            continue

        lote["status"] = "RODANDO"
        try:
            from nistiprint_shared.services.async_operation_service import async_operation_service
            async_operation_service.sync_ai_batch(lote)
        except Exception:
            logger.exception("Não foi possível retomar o acompanhamento do lote de IA %s", batch_id)

        if _tocar_campainha_do_batch(batch_id):
            retomados.append(batch_id)
        else:
            # Devolve para PENDENTE: sem isso o lote ficaria preso em RODANDO
            # sem ninguem processando, que e justamente o estado que esta task
            # existe para evitar.
            supabase_db.table("execucoes_ai_batch").update(
                {"status": "PENDENTE"}
            ).eq("id", batch_id).execute()
            lote["status"] = "PENDENTE"
            try:
                from nistiprint_shared.services.async_operation_service import async_operation_service
                async_operation_service.sync_ai_batch(lote)
            except Exception:
                logger.exception("Não foi possível atualizar fila do lote %s", batch_id)

    limite_rodando = (agora - timedelta(seconds=LOTE_RODANDO_TOLERANCIA_SEGUNDOS)).isoformat()
    travados = (
        supabase_db.table("execucoes_ai_batch")
        .select("id,total,processados,sucesso,falha,status,criado_em,finalizado_em,iniciado_por")
        .eq("status", "RODANDO")
        .lt("criado_em", limite_rodando)
        .execute()
        .data
        or []
    )

    for lote in travados:
        has_account_groups = (supabase_db.table("execucoes_ai_batch_conta")
                              .select("batch_id").eq("batch_id", lote["id"])
                              .limit(1).execute().data or [])
        if has_account_groups:
            continue
        if (lote.get("processados") or 0) >= (lote.get("total") or 0):
            # Terminou mas nao foi finalizado: o incremento do ultimo item
            # falhou depois de processar. Fechar como CONCLUIDO e mais fiel ao
            # que de fato aconteceu do que marcar erro.
            supabase_db.table("execucoes_ai_batch").update({
                "status": "CONCLUIDO",
                "finalizado_em": agora.isoformat(),
            }).eq("id", lote["id"]).eq("status", "RODANDO").execute()
            lote.update({"status": "CONCLUIDO", "finalizado_em": agora.isoformat()})
            try:
                from nistiprint_shared.services.async_operation_service import async_operation_service
                async_operation_service.sync_ai_batch(lote)
            except Exception:
                logger.exception("Não foi possível finalizar acompanhamento do lote %s", lote["id"])
            continue

        supabase_db.table("execucoes_ai_batch").update({
            "status": "ERRO",
            "finalizado_em": agora.isoformat(),
        }).eq("id", lote["id"]).eq("status", "RODANDO").execute()
        lote.update({"status": "ERRO", "finalizado_em": agora.isoformat()})
        try:
            from nistiprint_shared.services.async_operation_service import async_operation_service
            async_operation_service.sync_ai_batch(lote)
        except Exception:
            logger.exception("Não foi possível registrar falha do lote %s", lote["id"])
        encerrados.append(lote["id"])

    if retomados or encerrados:
        logger.info(
            "Varredura de lotes de IA: %s retomado(s), %s encerrado(s) por inatividade.",
            len(retomados), len(encerrados),
        )

    return {"retomados": retomados, "encerrados": encerrados}


@shared_task(name="services.ai_personalization.processar_pendentes", bind=True)
def processar_pendentes_agendado(self, limit=None):
    """Lote periodico de extracao de personalizacao.

    Existe para que a tela de personalizados chegue de manha ja processada, em
    vez de depender de alguem lembrar de clicar em "Extrair nomes pendentes".

    Roda exatamente a mesma selecao do botao manual — `process_orders` sem
    `force`, que filtra por `should_process_order`. Isso e o ponto: pedido ja
    processado e sem mensagem nova do comprador nao volta para a IA, entao a
    execucao diaria nao gera custo repetido nem sobrescreve nome ja extraido.
    Duplicar a regra aqui seria a maneira mais facil de as duas divergirem.

    `limit=None` processa todos os pendentes. A execucao e barata quando nao ha
    nada: `select_orders_for_processing` devolve lista vazia e nenhum batch e
    criado.
    """
    try:
        success, message, payload = process_orders(limit=limit, respect_account_limit=False,
                                                   source="scheduled")
    except Exception as exc:
        logger.error("Lote agendado de personalizados falhou: %s", exc, exc_info=True)
        raise

    total = (payload or {}).get("total", 0) if isinstance(payload, dict) else 0
    logger.info("Lote agendado de personalizados: %s (agendados=%s)", message, total)
    return {"success": success, "message": message, "total": total}


def process_orders(limit=None, order_sn=None, pedido_ids=None, force=False, integration_id=None, iniciado_por=None,
                   dispatch=True, respect_account_limit=True, source="manual"):
    effective_limit = limit
    if limit in (0, "0", ""):
        effective_limit = None

    candidates, skipped = select_orders_for_processing(
        order_sn=order_sn,
        pedido_ids=pedido_ids,
        limit=effective_limit,
        force=force,
        integration_id=integration_id,
        respect_account_limit=respect_account_limit,
    )

    if not candidates:
        return True, "Nada a processar.", {
            "processed": [],
            "skipped": skipped,
            "status": "up_to_date" if skipped else "empty",
        }

    batch = create_processing_batch(
        candidates,
        skipped=skipped,
        iniciado_por=iniciado_por,
        force=force,
        dispatch=dispatch,
        source=source,
    )
    if not dispatch:
        return True, f"Lote de {batch['total']} pedido(s) registrado para início imediato.", batch
    if not batch.get("enfileirado"):
        # Sucesso, e nao erro: o lote esta registrado e sera processado. O que
        # muda e o "quando", e a mensagem precisa dizer isso — prometer inicio
        # imediato aqui faria a tela ficar esperando um progresso que ainda
        # nao comecou.
        return True, (
            f"Lote de {batch['total']} pedido(s) registrado. A fila nao respondeu agora; "
            "o processamento sera retomado automaticamente na proxima varredura."
        ), batch
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


def get_chat_messages(username, limit=None, integration_id=None, buyer_id=None):
    if not username and buyer_id in (None, ""):
        return []
    if buyer_id not in (None, "") and integration_id is None:
        raise ValueError("integration_id obrigatorio para busca por buyer_id")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=CHAT_LOOKBACK_DAYS)).isoformat()
    conversation_ids = []
    if buyer_id not in (None, ""):
        conversations = (supabase_db.table("conversas_chat_shopee")
                         .select("conversation_id")
                         .eq("buyer_user_id", int(buyer_id))
                         .eq("installed_integration_id", int(integration_id))
                         .execute().data or [])
        conversation_ids = [row["conversation_id"] for row in conversations]

    def fetch(field, value):
        rows = []
        start = 0
        while True:
            query = (supabase_db.table("view_mensagens_chat_ai_v2").select("*")
                     .eq(field, value).gte("created_at", cutoff)
                     .order("created_at", desc=True).range(start, start + 499))
            if integration_id is not None:
                query = query.eq("installed_integration_id", int(integration_id))
            page = query.execute().data or []
            rows.extend(page)
            if len(page) < 500:
                return rows
            start += 500

    rows = []
    for cid in conversation_ids:
        rows.extend(fetch("conversation_id", cid))
    if buyer_id not in (None, ""):
        rows.extend(fetch("from_id", int(buyer_id)))
        rows.extend(fetch("to_id", int(buyer_id)))
    if username:
        for field in ("from_user_name", "to_user_name"):
            for row in fetch(field, username):
                if buyer_id in (None, "") or (
                    row.get("from_id") in (None, "") and row.get("to_id") in (None, "")
                ):
                    rows.append(row)
    messages = list({str(row.get("id")): row for row in rows}.values())
    messages.sort(key=lambda row: (_parse_datetime(row.get("created_at")) or
                                   datetime.min.replace(tzinfo=timezone.utc), str(row.get("id"))))
    if limit:
        messages = messages[-int(limit):]
    return compact_chat_messages(messages, username or "", buyer_id=buyer_id)


def get_orders_with_chats(order_sn=None, limit=None, situacao_ids=None,
                          pedido_ids=None, numero_pedido_prefix=None):
    rows = _assemble_orders(
        order_sn=order_sn,
        pedido_ids=pedido_ids,
        limit=limit,
        recent_days=None,
        situacao_ids=situacao_ids,
        numero_pedido_prefix=numero_pedido_prefix,
    )
    normalized_orders = [_normalize_order_row(row) for row in rows]
    if limit:
        return normalized_orders[:limit]
    return normalized_orders
