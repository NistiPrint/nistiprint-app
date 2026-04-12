"""
Endpoints de debug para rastreamento e diagnóstico.
"""

from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("DebugAPI")

debug_bp = Blueprint('debug', __name__, url_prefix='/api/v2/debug')


@debug_bp.route('/pedido/<int:pedido_id>/rastreamento-completo', methods=['GET'])
@login_required
def get_pedido_rastreamento(pedido_id):
    """
    Retorna rastreamento completo de um pedido:
    - Dados do pedido
    - Demandas vinculadas
    - Itens do pedido
    - Histórico de personalizações
    """
    try:
        # 1. Dados do pedido
        pedido_res = supabase_db.table('pedidos').select('''
            *,
            situacao_pedido:situacoes_pedido(nome, cor_status),
            canal_venda:canais_venda(nome)
        ''').eq('id', pedido_id).single().execute()

        if not pedido_res.data:
            return ApiResponse.error(message=f"Pedido {pedido_id} não encontrado", status_code=404)

        pedido = pedido_res.data

        # 2. Demandas vinculadas via view
        demandas_res = supabase_db.table('v_pedido_demanda_rastreamento').select('*').eq('pedido_id', pedido_id).execute()
        demandas = demandas_res.data or []

        # 3. Demandas via pivot (confirmação)
        pivot_res = supabase_db.table('demandas_pedidos').select('''
            demanda_id,
            demandas_producao(
                id, demanda_id, descricao, status, tipo_demanda, is_flex, created_at
            )
        ''').eq('pedido_id', pedido_id).execute()
        pivot_demandas = pivot_res.data or []

        # 4. Itens do pedido
        itens_res = supabase_db.table('itens_pedido').select('*').eq('pedido_id', pedido_id).execute()
        itens = itens_res.data or []

        # 5. Logs de IA
        logs_res = supabase_db.table('logs_execucao_ia').select('*').eq('order_sn', pedido.get('numero_loja')).order('executed_at', desc=True).execute()
        logs_ia = logs_res.data or []

        return ApiResponse.success(data={
            'pedido': {
                'id': pedido.get('id'),
                'numero_pedido': pedido.get('numero_pedido'),
                'codigo_externo': pedido.get('codigo_pedido_externo'),
                'origem': pedido.get('origem'),
                'is_flex': pedido.get('is_flex'),
                'personalizado': pedido.get('personalizado'),
                'status': pedido.get('situacao_pedido'),
                'canal': pedido.get('canal_venda'),
            },
            'demandas_view': demandas,
            'demandas_pivot': pivot_demandas,
            'itens': itens,
            'logs_ia': logs_ia,
        })

    except Exception as e:
        logger.error(f"Erro no debug de pedido {pedido_id}: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@debug_bp.route('/demanda/<demanda_id>/rastreamento', methods=['GET'])
@login_required
def get_demanda_rastreamento(demanda_id):
    """
    Retorna pedidos origem de uma demanda via view.
    """
    try:
        # Via view
        view_res = supabase_db.table('v_pedido_demanda_rastreamento').select('*').eq('demanda_id', demanda_id).execute()

        # Via pivot
        demanda_res = supabase_db.table('demandas_producao').select('id').eq('demanda_id', demanda_id).single().execute()
        if not demanda_res.data:
            return ApiResponse.error(message=f"Demanda {demanda_id} não encontrada", status_code=404)

        demanda_internal_id = demanda_res.data['id']
        pivot_res = supabase_db.table('demandas_pedidos').select('''
            pedido_id,
            pedidos(
                id, numero_pedido, codigo_pedido_externo, cliente_nome, origem, is_flex, personalizado
            )
        ''').eq('demanda_id', demanda_internal_id).execute()

        return ApiResponse.success(data={
            'demanda_id': demanda_id,
            'pedidos_view': view_res.data or [],
            'pedidos_pivot': pivot_res.data or [],
        })

    except Exception as e:
        logger.error(f"Erro no debug de demanda {demanda_id}: {e}")
        return ApiResponse.error(message=str(e), status_code=500)
