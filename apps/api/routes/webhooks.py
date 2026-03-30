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

        if codigo_pedido_externo:
            demandas_ativas = supabase_db.rpc('get_demandas_ativas_com_pedido', {
                'p_pedido_externo_id': codigo_pedido_externo
            }).execute()

            # 4. Para cada demanda afetada, criar alerta
            if demandas_ativas.data:
                for demanda in demandas_ativas.data:
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

                    logger.info(f"Alerta criado para demanda {demanda['demanda_id']} devido ao cancelamento do pedido {codigo_pedido_externo}")

        return ApiResponse.success(data={
            'pedido_id': pedido_id,
            'codigo_pedido_externo': codigo_pedido_externo,
            'status': 'CANCELADO',
            'demandas_afetadas': len(demandas_ativas.data) if demandas_ativas.data else 0
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
        # Buscar itens da demanda que têm este pedido como origem
        itens_afetados = []
        total_qtd_reduzida = 0

        # Buscar vínculos do pedido com itens da demanda
        # Nota: Esta query pode precisar de ajuste dependendo da estrutura exata
        vinculos = supabase_db.table('demandas_item_origem').select('''
            demanda_item_id,
            quantidade_atendida,
            sku_externo,
            item:itens_demanda(
                id,
                sku,
                descricao,
                quantidade
            )
        ''').eq('demanda_id', demanda_internal_id).execute()

        if vinculos.data:
            # Filtrar manualmente por pedido (a query acima pode precisar de RPC)
            pedido_externo_ids = set()
            pedido_res = supabase_db.table('pedidos').select('codigo_pedido_externo').eq('id', pedido_id).single().execute()
            if pedido_res.data:
                pedido_externo_ids.add(pedido_res.data['codigo_pedido_externo'])
            
            for vinculo in vinculos.data:
                if vinculo.get('pedido_externo_id') in pedido_externo_ids:
                    item = vinculo.get('item')
                    if item:
                        qtd_original = float(item.get('quantidade', 0))
                        qtd_pedido = float(vinculo.get('quantidade_atendida', 0))
                        qtd_nova = qtd_original - qtd_pedido

                        itens_afetados.append({
                            'item_id': item.get('id'),
                            'sku': item.get('sku') or vinculo.get('sku_externo'),
                            'descricao': item.get('descricao'),
                            'qtd_original': qtd_original,
                            'qtd_pedido_cancelado': qtd_pedido,
                            'qtd_nova': max(0, qtd_nova)
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
