"""
Endpoints para gestao de pedidos personalizados com IA.
"""

import logging

from flask import Blueprint, g, request

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.ai import AIProviderError
from nistiprint_shared.services.ai_personalization_service import (
    delete_logs,
    get_ai_config,
    get_all_logs,
    get_chat_messages,
    get_logs_by_order_sn,
    get_orders_with_chats,
    process_orders,
    save_feedback,
    update_ai_config,
)
from routes.auth import admin_required, check_permission, get_current_user
from utils.api_response import ApiResponse

logger = logging.getLogger("PersonalizadosAPI")

personalizados_bp = Blueprint("personalizados", __name__)


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _parse_id_list(value):
    if value in (None, "", []):
        return None
    if isinstance(value, list):
        parsed = []
        for item in value:
            try:
                parsed.append(int(item))
            except (TypeError, ValueError):
                continue
        return parsed or None
    if isinstance(value, str):
        parsed = []
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                parsed.append(int(item))
            except ValueError:
                continue
        return parsed or None
    return None


@personalizados_bp.route("", methods=["GET"])
@check_permission("vendas", "ler")
def listar_personalizados():
    try:
        order_sn = request.args.get("order_sn")
        limit = request.args.get("limit", type=int)
        orders = get_orders_with_chats(order_sn=order_sn, limit=limit)
        return ApiResponse.success({"orders": orders, "total": len(orders)})
    except Exception as exc:
        logger.error("Erro ao listar pedidos personalizados: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/processar", methods=["POST"])
@check_permission("vendas", "editar")
def processar():
    try:
        body = request.get_json(silent=True) or {}
        pedido_ids = body.get("pedido_ids")
        order_sn = body.get("order_sn")
        limit = body.get("limit")
        integration_id = body.get("integration_id")
        force = _parse_bool(body.get("force"))
        user = get_current_user()

        success, message, payload = process_orders(
            limit=limit,
            order_sn=order_sn,
            pedido_ids=pedido_ids,
            force=force,
            integration_id=integration_id,
            iniciado_por=user.get("id") if user else None,
        )
        if not success:
            return ApiResponse.error(message, 500)

        status_code = 200 if order_sn else 202
        return ApiResponse.success(payload, message=message, status_code=status_code)
    except Exception as exc:
        logger.error("Erro ao iniciar processamento de IA: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/processar/<batch_id>", methods=["GET"])
@check_permission("vendas", "ler")
def progresso(batch_id):
    try:
        user = get_current_user()
        response = (
            supabase_db.table("execucoes_ai_batch")
            .select("*")
            .eq("id", batch_id)
            .maybe_single()
            .execute()
        )
        if not response.data:
            return ApiResponse.error("Batch nao encontrado", 404)
        if str(response.data.get("iniciado_por") or "") != str(user.get("id") if user else ""):
            return ApiResponse.error("Batch nao encontrado", 404)
        return ApiResponse.success(response.data)
    except Exception as exc:
        logger.error("Erro ao consultar batch %s: %s", batch_id, exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/processar/<batch_id>/itens", methods=["GET"])
@check_permission("vendas", "ler")
def itens_batch(batch_id):
    try:
        user = get_current_user()
        batch = (
            supabase_db.table("execucoes_ai_batch")
            .select("id,iniciado_por")
            .eq("id", batch_id)
            .maybe_single()
            .execute()
            .data
        )
        if not batch or str(batch.get("iniciado_por") or "") != str(user.get("id") if user else ""):
            return ApiResponse.error("Batch nao encontrado", 404)
        response = (
            supabase_db.table("execucoes_ai_item")
            .select("*")
            .eq("batch_id", batch_id)
            .order("criado_em", desc=False)
            .execute()
        )
        itens = response.data or []
        return ApiResponse.success({"items": itens, "total": len(itens)})
    except Exception as exc:
        logger.error("Erro ao listar itens do batch %s: %s", batch_id, exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/logs", methods=["GET"])
@check_permission("vendas", "ler")
def listar_logs():
    try:
        order_sn = request.args.get("order_sn")
        status = request.args.get("status")
        limit = max(1, min(200, request.args.get("limit", default=50, type=int)))
        offset = max(0, request.args.get("offset", default=0, type=int))
        logs = get_all_logs(order_sn=order_sn, status=status, limit=limit, offset=offset)
        return ApiResponse.success(logs)
    except Exception as exc:
        logger.error("Erro ao listar logs de IA: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/logs", methods=["DELETE"])
@admin_required
def limpar_logs():
    try:
        order_sn = request.args.get("order_sn")
        status = request.args.get("status")
        delete_all = _parse_bool(request.args.get("all"))
        deleted_count = delete_logs(order_sn=order_sn, status=status, delete_all=delete_all)
        return ApiResponse.success(
            {"deleted_count": deleted_count},
            message=f"{deleted_count} log(s) deletado(s).",
        )
    except ValueError as exc:
        return ApiResponse.error(str(exc), 400)
    except Exception as exc:
        logger.error("Erro ao deletar logs de IA: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/logs/<order_sn>", methods=["GET"])
@check_permission("vendas", "ler")
def get_logs(order_sn):
    try:
        logs = get_logs_by_order_sn(order_sn)
        return ApiResponse.success({"logs": logs, "total": len(logs)})
    except Exception as exc:
        logger.error("Erro ao consultar logs do pedido %s: %s", order_sn, exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/logs/<order_sn>", methods=["DELETE"])
@admin_required
def delete_order_logs(order_sn):
    try:
        deleted_count = delete_logs(order_sn=order_sn)
        return ApiResponse.success(
            {"deleted_count": deleted_count},
            message=f"{deleted_count} log(s) deletado(s) para o pedido {order_sn}.",
        )
    except Exception as exc:
        logger.error("Erro ao deletar logs do pedido %s: %s", order_sn, exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/feedback", methods=["POST"])
@check_permission("vendas", "editar")
def feedback():
    try:
        body = request.get_json(silent=True) or {}
        order_sn = body.get("order_sn")
        avaliacao = body.get("avaliacao")
        texto_feedback = body.get("texto_feedback", "")

        if not order_sn:
            return ApiResponse.error("order_sn e obrigatorio", 400)
        if avaliacao is None:
            return ApiResponse.error("avaliacao e obrigatoria", 400)

        payload = save_feedback(order_sn, avaliacao, texto_feedback)
        return ApiResponse.success(payload, message="Feedback salvo com sucesso.")
    except Exception as exc:
        logger.error("Erro ao salvar feedback: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/config", methods=["GET"])
@admin_required
def get_config():
    try:
        return ApiResponse.success({"config": get_ai_config()})
    except Exception as exc:
        logger.error("Erro ao carregar configuracoes de IA: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/config", methods=["PUT"])
@admin_required
def put_config():
    try:
        body = request.get_json(silent=True) or {}
        config = update_ai_config(
            prompt_template=body.get("prompt_template"),
            model_name=body.get("model_name"),
            max_processing=body.get("max_processing"),
            provider=body.get("provider"),
            fallback_provider=body.get("fallback_provider"),
            timeout_seconds=body.get("timeout_seconds"),
        )
        return ApiResponse.success({"config": config}, message="Configuracoes atualizadas com sucesso.")
    except (ValueError, AIProviderError) as exc:
        # Par provedor/modelo invalido e erro do operador, nao do servidor.
        return ApiResponse.error(str(exc), 400)
    except Exception as exc:
        logger.error("Erro ao atualizar configuracoes de IA: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/chat/<username>", methods=["GET"])
@check_permission("vendas", "ler")
def chat(username):
    try:
        limit = request.args.get("limit", type=int)
        integration_id = request.args.get("integration_id", type=int)
        messages = get_chat_messages(username, limit=limit, integration_id=integration_id)
        return ApiResponse.success({"messages": messages, "total": len(messages)})
    except Exception as exc:
        logger.error("Erro ao carregar chat %s: %s", username, exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/reprocessar/<order_sn>", methods=["POST"])
@check_permission("vendas", "editar")
def reprocessar(order_sn):
    try:
        user = get_current_user()
        success, message, payload = process_orders(
            order_sn=order_sn, force=True,
            iniciado_por=user.get("id") if user else None,
        )
        if not success:
            return ApiResponse.error(message, 500)
        if isinstance(payload, dict):
            payload["reprocessed_by"] = getattr(g, "user_email", None)
        return ApiResponse.success(payload, message=message)
    except Exception as exc:
        logger.error("Erro ao reprocessar pedido %s: %s", order_sn, exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)


@personalizados_bp.route("/reclassificar-personalizado", methods=["POST"])
@check_permission("vendas", "editar")
def reclassificar_personalizado():
    try:
        body = request.get_json(silent=True) or {}
        pedido_ids = _parse_id_list(body.get("pedido_ids"))
        source = body.get("source") or "shopee"

        response = supabase_db.rpc(
            "repair_personalized_classification",
            {
                "p_pedido_ids": pedido_ids,
                "p_source": source,
            },
        ).execute()
        result = (response.data or [{}])[0]
        return ApiResponse.success(
            result,
            message="Classificacao de personalizados corrigida com sucesso.",
        )
    except Exception as exc:
        logger.error("Erro ao reclassificar personalizados: %s", exc, exc_info=True)
        return ApiResponse.error(str(exc), 500)
