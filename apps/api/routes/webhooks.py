"""
Endpoints para webhooks de cancelamento de pedidos.

NOTA: O recebimento de webhooks do Bling É FEITO PELO N8N.
Este arquivo contém apenas endpoints para cancelamentos manuais/internos.

Fluxo correto dos webhooks do Bling:
  Bling → n8n (valida HMAC) → Redis (fila) → Worker → Supabase

Ver: docs/02-features/webhooks_fluxo_correto.md
"""

from flask import Blueprint, request, jsonify
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.constants import (
    STATUS_PEDIDO_CANCELADO,
    ALERTA_PEDIDO_CANCELADO,
    ALERTA_SEVERIDADE_MEDIA,
)
from utils.api_response import ApiResponse
import logging
from datetime import datetime, timezone

logger = logging.getLogger("WebhooksPedidos")

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/api/v2/webhooks')


@webhooks_bp.route('/pedido-cancelado', methods=['POST'])
def handle_pedido_cancelado():
    """
    Webhook chamado quando um pedido é cancelado (uso interno ou sistemas externos).

    Payload esperado:
    {
        "pedido_id": 123,  # ID interno do pedido (opcional)
        "codigo_pedido_externo": "260318ABC123",  # ID externo (obrigatório se não tiver pedido_id)
        "status": "CANCELADO",
        "motivo": "Cliente solicitou cancelamento",
        "data_cancelamento": "2026-03-18T10:30:00Z"
    }

    Ações:
    1. Atualiza status do pedido para CANCELADO
    2. Busca demandas ativas com este pedido
    3. Cria alerta em cada demanda afetada
    4. Calcula impacto nos itens da demanda
    """
    try:
        data = request.get_json()

        pedido_id = data.get('pedido_id')
        codigo_pedido_externo = data.get('codigo_pedido_externo')
        motivo = data.get('motivo', 'Não informado')
        data_cancelamento = data.get('data_cancelamento')

        # Validar dados mínimos
        if not pedido_id and not codigo_pedido_externo:
            return ApiResponse.error(
                message="pedido_id ou codigo_pedido_externo é obrigatório",
                status_code=400
            )

        # 1. Buscar pedido interno se não fornecido
        if not pedido_id and codigo_pedido_externo:
            pedido_res = supabase_db.table('pedidos').select('id').eq('codigo_pedido_externo', codigo_pedido_externo).single().execute()
            if pedido_res.data:
                pedido_id = pedido_res.data['id']

        if not pedido_id:
            return ApiResponse.error(
                message=f"Pedido não encontrado (externo: {codigo_pedido_externo})",
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
        # Primeiro obter codigo_pedido_externo se não temos
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
