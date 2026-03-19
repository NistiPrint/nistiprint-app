"""
Endpoints para alertas e notificações de produção.
"""

from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("AlertasAPI")

alertas_bp = Blueprint('alertas', __name__, url_prefix='/api/v2/alertas')


@alertas_bp.route('/validar-pedidos-demanda', methods=['POST'])
@login_required
def validar_pedidos_para_demanda():
    """
    Verifica se pedidos já estão em demandas ativas antes de criar nova demanda.
    
    Payload: { "pedido_ids": [1, 2, 3] }
    
    Retorna:
    {
      "pedidos_livres": [1, 3],
      "pedidos_em_demanda": [
        {
          "pedido_id": 2,
          "numero_pedido": "445012",
          "demanda_id": "uuid-123",
          "demanda_descricao": "Shopee Março",
          "demanda_status": "EM_PRODUCAO"
        }
      ],
      "requer_confirmacao": true
    }
    """
    try:
        data = request.get_json()
        pedido_ids = data.get('pedido_ids', [])
        
        if not pedido_ids:
            return ApiResponse.error(message="pedido_ids é obrigatório", status_code=400)
        
        # Buscar detalhes dos pedidos
        pedidos_response = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo
        ''').in_('id', pedido_ids).execute()
        
        pedidos = pedidos_response.data or []
        pedidos_map = {p['id']: p for p in pedidos}
        
        # Para cada pedido, verificar se está em demanda ativa
        pedidos_livres = []
        pedidos_em_demanda = []
        
        for pedido_id in pedido_ids:
            pedido = pedidos_map.get(pedido_id)
            if not pedido:
                continue
            
            # Buscar demandas ativas para este pedido
            demandas_ativas = supabase_db.table('demandas_producao').select('''
                demanda_id,
                descricao,
                status,
                data_entrega
            ''').eq('pedido_id', pedido_id).in_('status', [
                'AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'COLETADO'
            ]).execute()
            
            if demandas_ativas.data and len(demandas_ativas.data) > 0:
                # Pedido já está em demanda ativa
                demanda = demandas_ativas.data[0]
                pedidos_em_demanda.append({
                    'pedido_id': pedido_id,
                    'numero_pedido': pedido.get('numero_pedido'),
                    'codigo_externo': pedido.get('codigo_pedido_externo'),
                    'demanda_id': demanda.get('demanda_id'),
                    'demanda_descricao': demanda.get('descricao'),
                    'demanda_status': demanda.get('status'),
                    'data_entrega': demanda.get('data_entrega')
                })
            else:
                # Verificar via demandas_item_origem (para demandas consolidadas)
                vinculos = supabase_db.table('demandas_item_origem').select('''
                    demanda_item_id,
                    demanda:itens_demanda!inner(
                        demanda_id,
                        demanda_producao:demandas_producao!inner(
                            id,
                            demanda_id,
                            descricao,
                            status
                        )
                    )
                ''').eq('pedido_externo_id', pedido.get('codigo_pedido_externo')).execute()
                
                demanda_ativa_encontrada = None
                if vinculos.data:
                    for vinculo in vinculos.data:
                        demanda_data = vinculo.get('demanda', {}).get('demanda_producao')
                        if demanda_data and demanda_data.get('status') in ['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'COLETADO']:
                            demanda_ativa_encontrada = demanda_data
                            break
                
                if demanda_ativa_encontrada:
                    pedidos_em_demanda.append({
                        'pedido_id': pedido_id,
                        'numero_pedido': pedido.get('numero_pedido'),
                        'codigo_externo': pedido.get('codigo_pedido_externo'),
                        'demanda_id': demanda_ativa_encontrada.get('demanda_id'),
                        'demanda_descricao': demanda_ativa_encontrada.get('descricao'),
                        'demanda_status': demanda_ativa_encontrada.get('status'),
                        'data_entrega': None
                    })
                else:
                    pedidos_livres.append(pedido_id)
        
        return ApiResponse.success(data={
            'pedido_ids_originais': pedido_ids,
            'pedidos_livres': pedidos_livres,
            'pedidos_em_demanda': pedidos_em_demanda,
            'total_pedidos': len(pedido_ids),
            'total_livres': len(pedidos_livres),
            'total_em_demanda': len(pedidos_em_demanda),
            'requer_confirmacao': len(pedidos_em_demanda) > 0
        })
        
    except Exception as e:
        logger.error(f"Erro ao validar pedidos para demanda: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao validar pedidos: {str(e)}",
            status_code=500
        )


@alertas_bp.route('/producao', methods=['GET'])
@login_required
def get_alertas_producao():
    """
    Retorna alertas de produção ativos.
    
    Tipos de alerta:
    - PEDIDOS_ORFAOS: Pedidos sem demanda vinculada há mais de 24h
    - DEMANDAS_ATRASADAS: Demandas com data de entrega vencida
    - FLEX_URGENTE: Pedidos FLEX próximos do prazo
    - ESTOQUE_INSUFICIENTE: Demandas com estoque insuficiente
    """
    try:
        # Chamar função RPC
        result = supabase_db.rpc('get_alertas_producao').execute()
        
        alertas = result.data or []
        
        # Filtrar apenas alertas com quantidade > 0
        alertas_ativos = [a for a in alertas if a.get('quantidade', 0) > 0]
        
        # Ordenar por severidade (alta > media > baixa)
        severidade_order = {'alta': 0, 'media': 1, 'baixa': 2}
        alertas_ativos.sort(key=lambda x: severidade_order.get(x.get('severidade', 'baixa'), 3))
        
        # Resumo
        resumo = {
            'total_alertas': len(alertas_ativos),
            'alta': len([a for a in alertas_ativos if a.get('severidade') == 'alta']),
            'media': len([a for a in alertas_ativos if a.get('severidade') == 'media']),
            'baixa': len([a for a in alertas_ativos if a.get('severidade') == 'baixa'])
        }
        
        return ApiResponse.success(data={
            'alertas': alertas_ativos,
            'resumo': resumo
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar alertas de produção: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao buscar alertas: {str(e)}",
            status_code=500
        )


@alertas_bp.route('/producao/resumo', methods=['GET'])
@login_required
def get_resumo_alertas():
    """
    Retorna apenas o resumo dos alertas (para badges/contadores).
    """
    try:
        result = supabase_db.rpc('get_alertas_producao').execute()
        
        alertas = result.data or []
        alertas_ativos = [a for a in alertas if a.get('quantidade', 0) > 0]
        
        resumo = {
            'total_alertas': len(alertas_ativos),
            'pedidos_orfaos': next((a['quantidade'] for a in alertas if a.get('tipo_alerta') == 'PEDIDOS_ORFAOS'), 0),
            'demandas_atrasadas': next((a['quantidade'] for a in alertas if a.get('tipo_alerta') == 'DEMANDAS_ATRASADAS'), 0),
            'flex_urgente': next((a['quantidade'] for a in alertas if a.get('tipo_alerta') == 'FLEX_URGENTE'), 0),
            'estoque_insuficiente': next((a['quantidade'] for a in alertas if a.get('tipo_alerta') == 'ESTOQUE_INSUFICIENTE'), 0)
        }
        
        return ApiResponse.success(data=resumo)
        
    except Exception as e:
        logger.error(f"Erro ao buscar resumo de alertas: {e}")
        return ApiResponse.error(
            message=f"Erro ao buscar resumo: {str(e)}",
            status_code=500
        )


@alertas_bp.route('/pedidos-orfaos', methods=['GET'])
@login_required
def get_pedidos_orfaos():
    """
    Retorna lista detalhada de pedidos órfãos (sem demanda).
    
    Query params:
    - horas: Número mínimo de horas sem demanda (default: 24)
    - limit: Limite de resultados (default: 50)
    """
    try:
        horas = request.args.get('horas', 24, type=int)
        limit = request.args.get('limit', 50, type=int)
        
        # Buscar pedidos órfãos
        result = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo,
            cliente_nome,
            cliente_telefone,
            data_venda,
            data_limite_envio,
            total_pedido,
            is_flex,
            situacao_pedido:situacoes_pedido(nome, cor_status),
            canal_venda:canais_venda(nome),
            integracoes:vinculos_integracao_pedido(plataforma, id_na_plataforma)
        ''').eq('situacao_pedido_id', 1).or_('situacao_pedido_id.eq.2').order('data_venda', desc=True).limit(limit).execute()
        
        pedidos = result.data or []
        
        # Filtrar apenas pedidos sem demanda e com mais de X horas
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=horas)
        
        pedidos_orfaos = []
        for p in pedidos:
            # Verificar se tem demanda
            has_demanda = supabase_db.table('demandas_producao').select('id').eq('pedido_id', p['id']).execute()
            
            if not has_demanda.data:
                data_venda = p.get('data_venda')
                if data_venda:
                    if isinstance(data_venda, str):
                        data_venda = datetime.fromisoformat(data_venda.replace('Z', '+00:00'))
                    if data_venda.tzinfo is None:
                        data_venda = data_venda.replace(tzinfo=timezone.utc)
                    
                    if data_venda < cutoff:
                        horas_sem_demanda = (datetime.now(timezone.utc) - data_venda).total_seconds() / 3600
                        pedidos_orfaos.append({
                            **p,
                            'horas_sem_demanda': round(horas_sem_demanda, 1)
                        })
        
        return ApiResponse.success(data={
            'pedidos': pedidos_orfaos[:limit],
            'total': len(pedidos_orfaos),
            'horas_minimas': horas
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos órfãos: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao buscar pedidos órfãos: {str(e)}",
            status_code=500
        )
