from flask import Blueprint, request, jsonify
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
from nistiprint_shared.services.product_service import product_service
import logging

logger = logging.getLogger("ConsolidarBase")
consolidar_base_bp = Blueprint('consolidar_base', __name__)

@consolidar_base_bp.route('/pedidos', methods=['GET'])
def get_pedidos_disponiveis():
    """
    Lista pedidos do banco que estão prontos para serem consolidados.
    Filtros via query params: plataforma_id, is_flex, data_inicio, data_fim, search
    """
    try:
        plataforma_id = request.args.get('plataforma_id', type=int)
        is_flex = request.args.get('is_flex', type=bool)
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        search = request.args.get('search')

        params = {
            'p_plataforma_id': plataforma_id,
            'p_is_flex': is_flex,
            'p_data_inicio': data_inicio,
            'p_data_fim': data_fim,
            'p_search': search
        }

        # Chama a RPC no Supabase
        res = supabase_db.rpc('get_pedidos_para_consolidar', params).execute()
        
        return ApiResponse.success(res.data)
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos para consolidar: {e}")
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
                    'pedido_id': p['pedido_id'],
                    'codigo_pedido_externo': p['codigo_pedido_externo'],
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
