"""
Endpoints para webhooks de cancelamento de pedidos.

NOTA: O recebimento de webhooks do Bling Ã‰ FEITO PELO N8N.
Este arquivo contÃ©m apenas endpoints para cancelamentos manuais/internos.

Fluxo correto dos webhooks do Bling:
  Bling â†’ n8n (valida HMAC) â†’ Redis (fila) â†’ Worker â†’ Supabase

Ver: docs/02-features/webhooks_fluxo_correto.md
"""

import os
from flask import Blueprint, request, jsonify
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.redis_queue_tasks import (
    LIVE_QUEUE_ALIASES,
    MERCADOLIVRE_WEBHOOK_QUEUE,
    SHOPEE_WEBHOOK_QUEUE,
    _serialize_queue_item,
    clear_queue,
    get_queue_items,
    get_queue_stats,
    get_redis_client,
    move_items,
    enqueue_marketplace_webhook_event,
)
from nistiprint_shared.services.webhook_monitoring_service import webhook_monitoring_service
from nistiprint_shared.services.marketplace_lifecycle_tasks import (
    reconcile_marketplace_lifecycle_task,
)
from nistiprint_shared.constants import (
    STATUS_PEDIDO_CANCELADO,
    ALERTA_PEDIDO_CANCELADO,
    ALERTA_SEVERIDADE_MEDIA,
)
from routes.auth import admin_required
from utils.api_response import ApiResponse
import logging
from datetime import datetime, timezone

logger = logging.getLogger("WebhooksPedidos")

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/api/v2/webhooks')


def _marketplace_webhook_authorized():
    expected = os.environ.get('MARKETPLACE_WEBHOOK_TOKEN')
    if not expected:
        return True
    provided = request.headers.get('X-Webhook-Token') or request.args.get('token')
    return provided == expected


def _enqueue_marketplace_webhook(source: str, queue_name: str):
    if not _marketplace_webhook_authorized():
        return jsonify({'success': False, 'error': 'webhook token invalido'}), 403

    payload = request.get_json(silent=True) or {}
    queued = enqueue_marketplace_webhook_event(source, payload, queue_name=queue_name)
    if not queued.get('event_id'):
        return jsonify({
            'success': False,
            'source': source,
            'queued': False,
            'error': 'falha ao persistir webhook',
        }), 503
    return jsonify({
        'success': True,
        'source': source,
        'queued': bool(queued.get('event_id')),
        'queue': queue_name,
        'webhook_event_id': queued.get('event_id'),
    }), 202


@webhooks_bp.route('/shopee', methods=['POST'])
def receive_shopee_webhook():
    return _enqueue_marketplace_webhook('shopee', SHOPEE_WEBHOOK_QUEUE)


@webhooks_bp.route('/mercadolivre', methods=['POST'])
def receive_mercadolivre_webhook():
    return _enqueue_marketplace_webhook('mercadolivre', MERCADOLIVRE_WEBHOOK_QUEUE)


@webhooks_bp.route('/marketplace/reconcile', methods=['POST'])
@admin_required
def reconcile_marketplace_orders():
    """Queue a bounded marketplace reconciliation run."""
    data = request.get_json(silent=True) or {}
    apply_changes = bool(data.get('apply', False))
    days = min(max(int(data.get('days', 60)), 1), 90)
    limit = min(max(int(data.get('limit', 100)), 1), 100)
    offset = max(int(data.get('offset', 0)), 0)
    task = reconcile_marketplace_lifecycle_task.delay(
        dry_run=not apply_changes,
        days=days,
        limit=limit,
        offset=offset,
        projection_enabled=apply_changes,
        continue_batches=True,
    )
    return jsonify({
        'success': True,
        'queued': True,
        'task_id': task.id,
        'dry_run': not apply_changes,
        'days': days,
        'limit': limit,
        'offset': offset,
    }), 202


@webhooks_bp.route('/events', methods=['GET'])
@admin_required
def list_webhook_events():
    try:
        filters = {
            'source': request.args.get('source') or 'bling',
            'status': request.args.get('status'),
            'bling_id': request.args.get('bling_id'),
            'numero_loja': request.args.get('numero_loja'),
            'pedido_id': request.args.get('pedido_id'),
            'correlation_id': request.args.get('correlation_id'),
            'since': request.args.get('since'),
            'until': request.args.get('until'),
            'page': request.args.get('page', 1),
            'per_page': request.args.get('per_page', 50),
        }
        result = webhook_monitoring_service.list_events(filters)
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error("Erro ao listar webhook_events: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/events/<int:event_id>', methods=['GET'])
@admin_required
def get_webhook_event(event_id):
    try:
        event = webhook_monitoring_service.get_event(event_id)
        if not event:
            return jsonify({'success': False, 'error': 'Evento de webhook nao encontrado'}), 404
        return jsonify({'success': True, 'event': event})
    except Exception as e:
        logger.error("Erro ao buscar webhook_event id=%s: %s", event_id, e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/events/<int:event_id>/logs', methods=['GET'])
@admin_required
def get_webhook_event_logs(event_id):
    try:
        result = webhook_monitoring_service.get_event_logs(event_id)
        if not result:
            return jsonify({'success': False, 'error': 'Evento de webhook nao encontrado'}), 404
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error("Erro ao buscar logs do webhook_event id=%s: %s", event_id, e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/events/<int:event_id>/reprocess', methods=['POST'])
@admin_required
def reprocess_webhook_event(event_id):
    try:
        result = webhook_monitoring_service.reprocess_event(event_id)
        if not result.get('success'):
            return jsonify(result), result.get('status_code', 500)
        return jsonify(result)
    except Exception as e:
        logger.error("Erro ao reprocessar webhook_event id=%s: %s", event_id, e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/queue/stats', methods=['GET'])
@admin_required
def get_webhook_queue_stats():
    try:
        stats = get_queue_stats()
        stats['processados'] = webhook_monitoring_service.get_processed_count()
        return jsonify(stats)
    except Exception as e:
        logger.error("Erro ao buscar stats de filas de webhook: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/queue/items', methods=['GET'])
@admin_required
def get_webhook_queue_items():
    try:
        queue = request.args.get('queue', 'pendentes')
        limit = min(max(int(request.args.get('limit', 20)), 1), 100)
        if queue == 'processados':
            items = webhook_monitoring_service.list_processed_items(limit=limit)
        else:
            items = get_queue_items(queue, limit=limit)
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        logger.error("Erro ao listar itens de fila de webhook: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/queue/reprocess', methods=['POST'])
@admin_required
def reprocess_webhook_queue():
    try:
        data = request.get_json(silent=True) or {}
        source = data.get('source')
        reprocessable = (
            'falhas',
            'dead_letter',
            'shopee_falhas',
            'shopee_dead_letter',
            'mercadolivre_falhas',
            'mercadolivre_dead_letter',
        )
        if source not in reprocessable:
            return jsonify({'success': False, 'error': 'source deve ser uma fila de falhas ou dead_letter'}), 400
        moved = move_items(source, destination='pendentes')
        return jsonify({'success': True, 'reprocessed': moved})
    except Exception as e:
        logger.error("Erro ao reprocessar fila de webhook: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/queue/clear', methods=['DELETE'])
@admin_required
def clear_webhook_queue():
    try:
        queue = request.args.get('queue')
        if queue == 'processados':
            return jsonify({'success': True, 'deleted': 0, 'message': 'Historico persistido nao e limpo pela fila Redis'})
        if queue not in LIVE_QUEUE_ALIASES:
            return jsonify({'success': False, 'error': 'queue invalida'}), 400
        deleted = clear_queue(queue)
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        logger.error("Erro ao limpar fila de webhook: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@webhooks_bp.route('/pedido-cancelado', methods=['POST'])
def handle_pedido_cancelado():
    """
    Webhook chamado quando um pedido Ã© cancelado (uso interno ou sistemas externos).

    Payload esperado:
    {
        "pedido_id": 123,  # ID interno do pedido (opcional)
        "codigo_pedido_externo": "260318ABC123",  # ID externo (obrigatÃ³rio se nÃ£o tiver pedido_id)
        "status": "CANCELADO",
        "motivo": "Cliente solicitou cancelamento",
        "data_cancelamento": "2026-03-18T10:30:00Z"
    }

    AÃ§Ãµes:
    1. Atualiza status do pedido para CANCELADO
    2. Busca demandas ativas com este pedido
    3. Cria alerta em cada demanda afetada
    4. Calcula impacto nos itens da demanda
    """
    try:
        data = request.get_json()

        pedido_id = data.get('pedido_id')
        codigo_pedido_externo = data.get('codigo_pedido_externo')
        motivo = data.get('motivo', 'NÃ£o informado')
        data_cancelamento = data.get('data_cancelamento')

        # Validar dados mÃ­nimos
        if not pedido_id and not codigo_pedido_externo:
            return ApiResponse.error(
                message="pedido_id ou codigo_pedido_externo Ã© obrigatÃ³rio",
                status_code=400
            )

        # 1. Buscar pedido interno se nÃ£o fornecido
        if not pedido_id and codigo_pedido_externo:
            pedido_res = supabase_db.table('pedidos').select('id').eq('codigo_pedido_externo', codigo_pedido_externo).single().execute()
            if pedido_res.data:
                pedido_id = pedido_res.data['id']

        if not pedido_id:
            return ApiResponse.error(
                message=f"Pedido nÃ£o encontrado (externo: {codigo_pedido_externo})",
                status_code=404
            )

        # 2. Atualizar status do pedido para CANCELADO
        supabase_db.table('pedidos').update({
            'situacao_pedido_id': STATUS_PEDIDO_CANCELADO,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', pedido_id).execute()

        # Registrar evento na timeline
        supabase_db.table('eventos_pedido').insert({
            'pedido_id': pedido_id,
            'tipo_evento': 'ORDER_CANCELLED_WEBHOOK',
            'descricao': f'Pedido cancelado via webhook: {motivo}',
            'status_para': str(STATUS_PEDIDO_CANCELADO),
            'metadata': {
                'motivo': motivo,
                'data_cancelamento': data_cancelamento,
                'webhook': True
            },
            'created_at': datetime.now(timezone.utc).isoformat()
        }).execute()

        # 3. Buscar demandas ativas com este pedido
        # Primeiro obter codigo_pedido_externo se nÃ£o temos
        if not codigo_pedido_externo:
            pedido_res = supabase_db.table('pedidos').select('codigo_pedido_externo').eq('id', pedido_id).single().execute()
            if pedido_res.data:
                codigo_pedido_externo = pedido_res.data['codigo_pedido_externo']

        demandas_ativas = []
        if pedido_id:
            demandas_response = supabase_db.table('demandas_pedidos').select('''
                id,
                demanda_id,
                demanda:demandas_producao!inner(
                    id,
                    demanda_id,
                    descricao,
                    status
                )
            ''').eq('pedido_id', pedido_id).execute()
            for vinculo in demandas_response.data or []:
                demanda = vinculo.get('demanda')
                if demanda and demanda.get('status') in ['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'COLETADO']:
                    demanda['vinculo_id'] = vinculo.get('id')
                    demanda['demanda_internal_id'] = demanda.get('id')
                    demandas_ativas.append(demanda)

            # 4. Para cada demanda afetada, criar alerta e marcar revisao
            if demandas_ativas:
                for demanda in demandas_ativas:
                    # Calcular impacto nos itens
                    impacto = calcular_impacto_cancelamento(demanda['demanda_internal_id'], pedido_id)

                    # Criar alerta
                    supabase_db.table('alertas_demanda').insert({
                        'demanda_id': demanda['demanda_internal_id'],
                        'tipo_alerta': ALERTA_PEDIDO_CANCELADO,
                        'severidade': ALERTA_SEVERIDADE_MEDIA,
                        'titulo': 'Pedido cancelado na demanda',
                        'mensagem': f'Pedido {codigo_pedido_externo} foi cancelado: {motivo}',
                        'dados_impacto': impacto,
                        'requer_acao': True,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }).execute()

                    supabase_db.table('demandas_producao').update({
                        'requer_revisao': True,
                        'updated_at': datetime.now(timezone.utc).isoformat()
                    }).eq('id', demanda['demanda_internal_id']).execute()

                    supabase_db.table('demandas_pedidos').delete() \
                        .eq('id', demanda['vinculo_id']) \
                        .execute()

                    logger.info(f"Alerta criado para demanda {demanda['demanda_id']} devido ao cancelamento do pedido {codigo_pedido_externo}")

        return ApiResponse.success(data={
            'pedido_id': pedido_id,
            'codigo_pedido_externo': codigo_pedido_externo,
            'status': 'CANCELADO',
            'demandas_afetadas': len(demandas_ativas)
        })

    except Exception as e:
        logger.error(f"Erro ao processar cancelamento de pedido: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao processar cancelamento: {str(e)}",
            status_code=500
        )


def calcular_impacto_cancelamento(demanda_internal_id: int, pedido_id: int) -> dict:
    """
    Calcula o impacto do cancelamento de um pedido nos itens de uma demanda.

    Retorna:
    {
        "itens_afetados": [
            {
                "item_id": 123,
                "sku": "ABC123",
                "descricao": "Produto X",
                "qtd_original": 10,
                "qtd_pedido_cancelado": 2,
                "qtd_nova": 8
            }
        ],
        "total_itens_afetados": 1,
        "total_qtd_reduzida": 2
    }
    """
    try:
        itens_afetados = []
        total_qtd_reduzida = 0

        itens_demanda_res = supabase_db.table('itens_demanda').select(
            'id, produto_id, sku, descricao, quantidade'
        ).eq('demanda_id', demanda_internal_id).execute()
        itens_pedido_res = supabase_db.table('itens_pedido').select(
            'produto_id, sku_externo, descricao, quantidade'
        ).eq('pedido_id', pedido_id).execute()

        itens_demanda = itens_demanda_res.data or []
        demanda_por_produto = {
            str(item.get('produto_id')): item
            for item in itens_demanda
            if item.get('produto_id') is not None
        }
        demanda_por_sku = {
            str(item.get('sku') or '').strip(): item
            for item in itens_demanda
            if item.get('sku')
        }

        for item_pedido in itens_pedido_res.data or []:
            produto_id = item_pedido.get('produto_id')
            sku_externo = str(item_pedido.get('sku_externo') or '').strip()
            item = None
            match_type = None

            if produto_id is not None:
                item = demanda_por_produto.get(str(produto_id))
                match_type = 'produto_id' if item else None
            if not item and sku_externo:
                item = demanda_por_sku.get(sku_externo)
                match_type = 'sku' if item else None

            if not item:
                continue

            qtd_original = max(0, float(item.get('quantidade', 0) or 0))
            qtd_pedido = max(0, float(item_pedido.get('quantidade', 0) or 0))
            qtd_nova = max(0, qtd_original - qtd_pedido)

            itens_afetados.append({
                'item_id': item.get('id'),
                'sku': item.get('sku') or sku_externo,
                'descricao': item.get('descricao') or item_pedido.get('descricao'),
                'qtd_original': qtd_original,
                'qtd_pedido_cancelado': qtd_pedido,
                'qtd_nova': qtd_nova,
                'match_type': match_type
            })

            total_qtd_reduzida += qtd_pedido

        return {
            'itens_afetados': itens_afetados,
            'total_itens_afetados': len(itens_afetados),
            'total_qtd_reduzida': total_qtd_reduzida,
            'pedido_cancelado_id': pedido_id
        }

    except Exception as e:
        logger.error(f"Erro ao calcular impacto do cancelamento: {e}")
        return {
            'itens_afetados': [],
            'total_itens_afetados': 0,
            'total_qtd_reduzida': 0,
            'error': str(e)
        }
