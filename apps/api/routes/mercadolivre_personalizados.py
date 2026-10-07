"""Account-scoped APIs for Mercado Livre private post-sale personalization."""
from __future__ import annotations

import logging

from flask import Blueprint, request, session

from nistiprint_shared.services import mercadolivre_personalization_service as service
from routes.auth import admin_required, check_permission
from utils.api_response import ApiResponse

logger = logging.getLogger("MercadoLivrePersonalizadosAPI")
mercadolivre_personalizados_bp = Blueprint("mercadolivre_personalizados", __name__)


def _user_id():
    value = session.get("user_id")
    return int(value) if value is not None else None


def _handle_error(exc):
    if isinstance(exc, LookupError):
        return ApiResponse.error(str(exc), 404)
    if isinstance(exc, ValueError):
        return ApiResponse.error(str(exc), 400)
    logger.error("Falha na API de personalização Mercado Livre: %s", exc,
                 exc_info=(type(exc), exc, exc.__traceback__))
    return ApiResponse.error("Falha ao processar operação Mercado Livre", 500)


@mercadolivre_personalizados_bp.get("/api/v2/mercadolivre/integracoes/personalizacoes")
@check_permission("vendas", "ler")
def listar_contas():
    try:
        return ApiResponse.success({"accounts": service.available_integrations()})
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/config"
)
@admin_required
def obter_config(integration_id):
    try:
        service._integration(integration_id, active=False)
        return ApiResponse.success({"config": service._settings(integration_id)})
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.put(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/config"
)
@admin_required
def salvar_config(integration_id):
    try:
        body = request.get_json(silent=True) or {}
        config = service.update_settings(integration_id, body, user_id=_user_id())
        return ApiResponse.success({"config": config}, message="Configuração da conta atualizada.")
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/pedidos"
)
@check_permission("vendas", "ler")
def listar_pedidos(integration_id):
    try:
        limit = request.args.get("limit", default=200, type=int)
        orders = service.list_personalized_orders(integration_id, limit=limit)
        return ApiResponse.success({"orders": orders, "total": len(orders)})
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/saude"
)
@check_permission("vendas", "ler")
def saude_conta(integration_id):
    try:
        return ApiResponse.success(service.account_health(integration_id))
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/pedidos/<int:pedido_id>/chat"
)
@check_permission("vendas", "ler")
def obter_chat(integration_id, pedido_id):
    try:
        return ApiResponse.success(service.conversation_for_order(integration_id, pedido_id))
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/conversas-pendentes"
)
@check_permission("vendas", "ler")
def conversas_pendentes(integration_id):
    try:
        rows = service.list_pending_conversations(integration_id)
        return ApiResponse.success({"conversations": rows, "total": len(rows)})
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/webhooks-pendentes"
)
@check_permission("vendas", "ler")
def webhooks_pendentes_conta(integration_id):
    try:
        rows = service.list_unmatched_notifications(integration_id)
        return ApiResponse.success({"events": rows, "total": len(rows)})
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/personalizacoes/webhooks-sem-vinculo"
)
@admin_required
def webhooks_sem_vinculo():
    try:
        rows = service.list_unmatched_notifications()
        return ApiResponse.success({"events": rows, "total": len(rows)})
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/pedidos/<int:pedido_id>/logs"
)
@check_permission("vendas", "ler")
def obter_logs(integration_id, pedido_id):
    try:
        logs = service.logs_for_order(integration_id, pedido_id)
        return ApiResponse.success({"logs": logs, "total": len(logs)})
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.delete(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/pedidos/<int:pedido_id>/logs"
)
@check_permission("vendas", "editar")
def deletar_logs(integration_id, pedido_id):
    try:
        deleted = service.delete_logs_for_order(integration_id, pedido_id)
        return ApiResponse.success({"deleted_count": deleted}, message=f"{deleted} log(s) deletado(s).")
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.post(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/pedidos/<int:pedido_id>/feedback"
)
@check_permission("vendas", "editar")
def relatar_problema(integration_id, pedido_id):
    try:
        body = request.get_json(silent=True) or {}
        feedback = service.save_order_feedback(
            integration_id, pedido_id, body.get("texto_feedback", ""), user_id=_user_id()
        )
        return ApiResponse.success(feedback, message="Obrigado pelo relato. Vamos analisar o ocorrido.")
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.post(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/extrair"
)
@check_permission("vendas", "editar")
def extrair(integration_id):
    try:
        body = request.get_json(silent=True) or {}
        pedido_ids = body.get("pedido_ids")
        if pedido_ids is not None and (not isinstance(pedido_ids, list)
                                       or any(isinstance(value, bool) or not str(value).isdigit()
                                              for value in pedido_ids)):
            return ApiResponse.error("pedido_ids deve ser uma lista de IDs inteiros", 400)
        try:
            limit = int(body.get("limit", 50))
        except (TypeError, ValueError):
            return ApiResponse.error("limit deve ser um inteiro entre 1 e 500", 400)
        if isinstance(body.get("limit", 50), bool) or not 1 <= limit <= 500:
            return ApiResponse.error("limit deve ser um inteiro entre 1 e 500", 400)
        result = service.queue_manual(
            integration_id,
            pedido_ids=[int(value) for value in pedido_ids] if pedido_ids else None,
            force=body.get("force") is True,
            limit=limit,
        )
        if result.get("batch_id"):
            from nistiprint_shared.services.mercadolivre_personalization_worker import submit_batch
            submit_batch(integration_id, result["batch_id"])
        return ApiResponse.success(result, message=result.get("message", "Lote criado."), status_code=202)
    except Exception as exc:
        return _handle_error(exc)


@mercadolivre_personalizados_bp.get(
    "/api/v2/mercadolivre/integracoes/<int:integration_id>/personalizados/lotes/<batch_id>"
)
@check_permission("vendas", "ler")
def progresso_lote(integration_id, batch_id):
    try:
        return ApiResponse.success(service.batch_status(integration_id, batch_id))
    except Exception as exc:
        return _handle_error(exc)
