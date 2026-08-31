from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("ConsolidarBase")
consolidar_base_bp = Blueprint('consolidar_base', __name__)


@consolidar_base_bp.route('/pedidos', methods=['GET'])
@login_required
def get_pedidos_disponiveis():
    """
    Lista pedidos do banco que estão prontos para serem consolidados.
    
    Query params:
    - plataforma_id: Filtrar por canal de venda
    - is_flex: Filtrar pedidos Flex
    - data_inicio, data_fim: Período de venda
    - search: Termo de busca
    - contexto: Filtro contextual ('mesmo_prazo', 'mesmo_canal', 'itens_similares')
    - pedido_id: ID do pedido de referência (para similares)
    """
    try:
        plataforma_id = request.args.get('plataforma_id', type=int)
        is_flex = request.args.get('is_flex', type=bool)
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        search = request.args.get('search')
        contexto = request.args.get('contexto')
        pedido_id = request.args.get('pedido_id', type=int)
        limit = request.args.get('limit', 50, type=int)
        
        # Se tiver filtro contextual, usar nova função RPC
        if contexto:
            res = supabase_db.rpc('get_pedidos_contexto_consolidacao', {
                'p_filtro_contexto': contexto,
                'p_canal_venda_id': plataforma_id,
                'p_data_limite_inicio': data_inicio,
                'p_data_limite_fim': data_fim,
                'p_limit': limit
            }).execute()
            
            return ApiResponse.success(res.data or [])
        
        # Se tiver pedido_id, buscar similares
        if pedido_id:
            res = supabase_db.rpc('get_pedidos_similares', {
                'p_pedido_id': pedido_id,
                'p_limit': limit
            }).execute()
            
            return ApiResponse.success(res.data or [])
        
        # Filtros tradicionais
        params = {
            'p_plataforma_id': plataforma_id,
            'p_is_flex': is_flex,
            'p_data_inicio': data_inicio,
            'p_data_fim': data_fim,
            'p_search': search
        }

        # Chama a RPC no Supabase
        res = supabase_db.rpc('get_pedidos_para_consolidar', params).execute()

        return ApiResponse.success(res.data or [])
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos para consolidar: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(str(e))
@consolidar_base_bp.route('/pedidos/<int:pedido_id>/similares', methods=['GET'])
@login_required
def get_pedidos_similares_endpoint(pedido_id):
    """
    Busca pedidos similares a um pedido específico para sugestão de consolidação.
    
    Query params:
    - limit: Limite de resultados (default: 10)
    """
    try:
        limit = request.args.get('limit', 10, type=int)
        
        res = supabase_db.rpc('get_pedidos_similares', {
            'p_pedido_id': pedido_id,
            'p_limit': limit
        }).execute()
        
        return ApiResponse.success(res.data or [])
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos similares: {e}")
        return ApiResponse.error(str(e))
