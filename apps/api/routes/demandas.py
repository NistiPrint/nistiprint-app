"""
Endpoints para gestão de demandas de produção.
"""

from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
import logging
from datetime import datetime, timezone

logger = logging.getLogger("DemandasAPI")

demandas_bp = Blueprint('demandas', __name__, url_prefix='/api/v2/demandas')


@demandas_bp.route('/<demanda_id>/pedidos', methods=['GET'])
@login_required
def get_demanda_pedidos(demanda_id):
    """
    Retorna pedidos vinculados a uma demanda específica.
    
    A relação é feita através de:
    demandas_producao → itens_demanda → demandas_item_origem → pedidos
    """
    try:
        # Buscar demanda para validar existência
        demanda_response = supabase_db.table('demandas_producao').select(
            'demanda_id, descricao, status'
        ).eq('demanda_id', demanda_id).single().execute()
        
        if not demanda_response.data:
            return ApiResponse.error(
                message=f"Demanda {demanda_id} não encontrada",
                status_code=404
            )
        
        # Buscar pedidos vinculados via demandas_item_origem
        # Join complexo para trazer dados do pedido
        pedidos_response = supabase_db.rpc(
            'get_pedidos_por_demanda',
            {'p_demanda_id': demanda_id}
        ).execute()
        
        if not pedidos_response.data:
            return ApiResponse.success(data={
                'demanda_id': demanda_id,
                'pedidos': [],
                'total_pedidos': 0,
                'total_itens': 0
            })
        
        # Processar resultados
        pedidos = []
        pedidos_vistos = set()
        
        for row in pedidos_response.data:
            pedido_externo_id = row.get('pedido_externo_id')
            
            # Evitar duplicatas
            if pedido_externo_id in pedidos_vistos:
                continue
            
            pedidos_vistos.add(pedido_externo_id)
            
            # Buscar dados completos do pedido
            pedido_completo = supabase_db.table('pedidos').select('''
                id,
                numero_pedido,
                codigo_pedido_externo,
                cliente_nome,
                cliente_documento,
                situacao_pedido:situacoes_pedido(nome, cor_status),
                data_venda,
                total_pedido
            ''').eq('codigo_pedido_externo', pedido_externo_id).single().execute()
            
            if pedido_completo.data:
                pedido = pedido_completo.data
                
                # Calcular total de itens atendidos para este pedido
                itens_atendidos = [
                    r for r in pedidos_response.data 
                    if r.get('pedido_externo_id') == pedido_externo_id
                ]
                total_itens_atendidos = sum(
                    float(r.get('quantidade_atendida', 0)) 
                    for r in itens_atendidos
                )
                
                pedidos.append({
                    'id': pedido.get('id'),
                    'numero_pedido': pedido.get('numero_pedido'),
                    'codigo_externo': pedido.get('codigo_pedido_externo'),
                    'cliente': {
                        'nome': pedido.get('cliente_nome'),
                        'documento': pedido.get('cliente_documento')
                    },
                    'status': {
                        'nome': pedido.get('situacao_pedido', {}).get('nome') if pedido.get('situacao_pedido') else 'Pendente',
                        'cor': pedido.get('situacao_pedido', {}).get('cor_status') if pedido.get('situacao_pedido') else '#f59e0b'
                    },
                    'data_venda': pedido.get('data_venda'),
                    'total_pedido': float(pedido.get('total_pedido', 0)) if pedido.get('total_pedido') else 0,
                    'itens_atendidos': total_itens_atendidos,
                    'qtd_itens_no_pedido': len(itens_atendidos)
                })
        
        return ApiResponse.success(data={
            'demanda_id': demanda_id,
            'demanda_descricao': demanda_response.data.get('descricao'),
            'demanda_status': demanda_response.data.get('status'),
            'pedidos': pedidos,
            'total_pedidos': len(pedidos),
            'total_itens': sum(p['qtd_itens_no_pedido'] for p in pedidos)
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos da demanda {demanda_id}: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao buscar pedidos: {str(e)}",
            status_code=500
        )


@demandas_bp.route('/<demanda_id>/timeline', methods=['GET'])
@login_required
def get_demanda_timeline(demanda_id):
    """
    Retorna timeline unificada de uma demanda.
    
    Combina:
    1. Eventos da demanda (criação, produção, coleta)
    2. Eventos dos pedidos vinculados (pago, enviado, cancelado)
    """
    try:
        # Buscar eventos da demanda (se houver tabela de eventos de demanda)
        # Por enquanto, usar dados da própria demanda
        demanda_response = supabase_db.table('demandas_producao').select(
            'demanda_id, descricao, created_at, data_entrega, status'
        ).eq('demanda_id', demanda_id).single().execute()
        
        if not demanda_response.data:
            return ApiResponse.error(
                message=f"Demanda {demanda_id} não encontrada",
                status_code=404
            )
        
        demanda = demanda_response.data
        
        # Buscar pedidos vinculados para obter seus eventos
        pedidos_response = supabase_db.rpc(
            'get_pedidos_por_demanda',
            {'p_demanda_id': demanda_id}
        ).execute()
        
        pedido_externo_ids = list(set(
            row.get('pedido_externo_id') 
            for row in (pedidos_response.data or [])
            if row.get('pedido_externo_id')
        ))
        
        # Buscar eventos dos pedidos
        eventos_pedido = []
        if pedido_externo_ids:
            eventos_response = supabase_db.table('eventos_pedido').select('''
                id,
                tipo_evento,
                descricao,
                status_de,
                status_para,
                created_at,
                metadata,
                pedido:pedidos(
                    id,
                    numero_pedido,
                    codigo_pedido_externo
                )
            ''').in_('codigo_pedido_externo', pedido_externo_ids).order('created_at', desc=True).execute()
            
            eventos_pedido = eventos_response.data or []
        
        # Construir timeline unificada
        timeline = []
        
        # Evento de criação da demanda
        timeline.append({
            'id': f'demanda-{demanda_id}-created',
            'tipo': 'demanda',
            'tipo_evento': 'DEMANDA_CREATED',
            'descricao': f'Demanda criada: {demanda.get("descricao", "Sem descrição")}',
            'created_at': demanda.get('created_at'),
            'metadata': {
                'demanda_id': demanda_id,
                'status': demanda.get('status'),
                'data_entrega': demanda.get('data_entrega')
            }
        })
        
        # Adicionar eventos dos pedidos
        for evento in eventos_pedido:
            pedido = evento.get('pedido', {})
            timeline.append({
                'id': f'pedido-{evento.get("id")}',
                'tipo': 'pedido',
                'tipo_evento': evento.get('tipo_evento'),
                'descricao': evento.get('descricao'),
                'created_at': evento.get('created_at'),
                'status_de': evento.get('status_de'),
                'status_para': evento.get('status_para'),
                'metadata': {
                    'pedido_numero': pedido.get('numero_pedido'),
                    'pedido_externo': pedido.get('codigo_pedido_externo'),
                    'demanda_id': demanda_id
                }
            })
        
        # Ordenar por data (mais recente primeiro)
        timeline.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        return ApiResponse.success(data={
            'demanda_id': demanda_id,
            'timeline': timeline,
            'total_eventos': len(timeline)
        })

    except Exception as e:
        logger.error(f"Erro ao buscar timeline da demanda {demanda_id}: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao buscar timeline: {str(e)}",
            status_code=500
        )


@demandas_bp.route('/<demanda_id>/alertas', methods=['GET'])
@login_required
def get_demanda_alertas(demanda_id):
    """
    Busca alertas de uma demanda específica.
    """
    try:
        # Buscar demanda para validar existência
        demanda_res = supabase_db.table('demandas_producao').select('id, demanda_id').eq('demanda_id', demanda_id).single().execute()
        
        if not demanda_res.data:
            return ApiResponse.error(
                message=f"Demanda {demanda_id} não encontrada",
                status_code=404
            )
        
        demanda_internal_id = demanda_res.data['id']
        
        # Buscar alertas da demanda
        alertas_res = supabase_db.table('alertas_demanda').select('*').eq('demanda_id', demanda_internal_id).order('created_at', desc=True).execute()
        
        return ApiResponse.success(data={
            'demanda_id': demanda_id,
            'alertas': alertas_res.data or [],
            'total': len(alertas_res.data) if alertas_res.data else 0
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar alertas da demanda {demanda_id}: {e}")
        return ApiResponse.error(
            message=f"Erro ao buscar alertas: {str(e)}",
            status_code=500
        )


@demandas_bp.route('/<demanda_id>/alertas/<int:alerta_id>/resolver', methods=['POST'])
@login_required
def resolver_alerta(demanda_id, alerta_id):
    """
    Marca um alerta como resolvido.
    """
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id')  # Virá do auth
        
        # Atualizar alerta
        update_res = supabase_db.table('alertas_demanda').update({
            'resolvido': True,
            'resolvido_em': datetime.now(timezone.utc).isoformat(),
            'resolvido_por': user_id
        }).eq('id', alerta_id).execute()
        
        if not update_res.data:
            return ApiResponse.error(
                message=f"Alerta {alerta_id} não encontrado",
                status_code=404
            )
        
        return ApiResponse.success(message="Alerta resolvido com sucesso")
        
    except Exception as e:
        logger.error(f"Erro ao resolver alerta {alerta_id}: {e}")
        return ApiResponse.error(
            message=f"Erro ao resolver alerta: {str(e)}",
            status_code=500
        )
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao buscar timeline: {str(e)}",
            status_code=500
        )
