from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
from nistiprint_shared.services.product_service import product_service
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

@consolidar_base_bp.route('/analisar', methods=['POST'])
def analisar_pedidos_selecionados():
    """
    Recebe uma lista de IDs de pedidos (do banco) e faz a análise de itens,
    resolvendo variações (variacao_id) igual ao ConsolidarPage faz com planilhas.
    """
    try:
        data = request.get_json()
        pedido_ids = data.get('pedido_ids', [])
        
        if not pedido_ids:
            return ApiResponse.error("Nenhum pedido selecionado.")

        # Busca os detalhes dos pedidos e seus itens
        # Como já temos a view que agrupa itens, podemos usá-la
        res = supabase_db.table('view_pedidos_para_consolidar').select('*').in_('pedido_id', pedido_ids).execute()
        
        pedidos = res.data
        if not pedidos:
            return ApiResponse.error("Pedidos não encontrados.")

        # Lógica de Consolidação (Normalização de Itens)
        # Similar ao que o FileProcessor faz
        consolidado = {}
        
        for p in pedidos:
            origem = p.get('plataforma_nome', 'DESCONHECIDA')
            for item in p.get('itens', []):
                sku = item.get('sku_externo')
                nome_item = item.get('descricao')
                qtd = float(item.get('quantidade', 0))
                
                # Resolvendo variação (Produto Interno)
                # Esta função do product_service faz a mágica de achar o ID interno
                resolved = product_service.resolve_variation(sku, origem, nome_item)
                
                key = (resolved['id'] if resolved else f"UNRESOLVED-{sku}", sku, nome_item)
                
                if key not in consolidado:
                    consolidado[key] = {
                        'produto_id': resolved['id'] if resolved else None,
                        'produto_nome': resolved['nome'] if resolved else nome_item,
                        'sku': sku,
                        'descricao_original': nome_item,
                        'quantidade': 0,
                        'pedidos': []
                    }
                
                consolidado[key]['quantidade'] += qtd
                consolidado[key]['pedidos'].append({
                    'pedido_id': p.get('pedido_id'), # Adicionado ID interno
                    'codigo_pedido_externo': p.get('codigo_pedido_externo'),
                    'quantidade': qtd
                })

        # Formata para o frontend
        resultado_lista = []
        for key, data in consolidado.items():
            resultado_lista.append(data)

        return ApiResponse.success({
            'total_pedidos': len(pedidos),
            'itens_consolidados': resultado_lista
        })

    except Exception as e:
        logger.error(f"Erro ao analisar pedidos selecionados: {e}")
        return ApiResponse.error(str(e))

@consolidar_base_bp.route('/plataformas', methods=['GET'])
def get_plataformas():
    """Lista as plataformas ativas para o filtro do frontend"""
    try:
        res = supabase_db.table('plataformas').select('id, nome').eq('ativa', True).execute()
        return ApiResponse.success(res.data)
    except Exception as e:
        return ApiResponse.error(str(e))
