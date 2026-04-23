"""
Endpoints para gestão de pedidos unificados.
"""

from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("PedidosAPI")

pedidos_bp = Blueprint('pedidos', __name__, url_prefix='/api/v2/pedidos')


@pedidos_bp.route('/<int:pedido_id>', methods=['GET'])
@login_required
def get_pedido_detalhe(pedido_id):
    """
    Retorna detalhes completos de um pedido específico.
    
    Inclui:
    - Dados principais do pedido
    - Itens do pedido
    - Integrações vinculadas (Bling, Shopee, etc.)
    - Timeline de eventos
    - Dados do canal de venda
    - Status atual
    """
    try:
        # Buscar pedido com todos os relacionamentos
        pedido_response = supabase_db.table('pedidos').select('''
            *,
            situacao_pedido:situacoes_pedido(
                id,
                nome,
                cor_status,
                descricao
            ),
            canal_venda:canais_venda(
                id,
                nome,
                slug,
                color
            ),
            itens_pedido:itens_pedido(
                id,
                sku_externo,
                descricao,
                quantidade,
                preco_unitario,
                subtotal,
                produto:produtos(
                    id,
                    nome,
                    sku
                )
            ),
            integracoes:vinculos_integracao_pedido(
                id,
                plataforma,
                id_na_plataforma,
                status_na_plataforma,
                dados_brutos,
                last_synced_at
            ),
            eventos:eventos_pedido(
                id,
                tipo_evento,
                descricao,
                status_de,
                status_para,
                created_at,
                metadata
            )
        ''').eq('id', pedido_id).single().execute()
        
        if not pedido_response.data:
            return ApiResponse.error(
                message=f"Pedido {pedido_id} não encontrado",
                status_code=404
            )
        
        pedido = pedido_response.data
        
        # Calcular totais
        total_itens = len(pedido.get('itens_pedido', []))
        total_quantidade = sum(float(item.get('quantidade', 0)) for item in pedido.get('itens_pedido', []))
        
        # Formatando dados para resposta
        resultado = {
            'id': pedido.get('id'),
            'uuid_pedido': pedido.get('uuid_pedido'),
            'numero_pedido': pedido.get('numero_pedido'),
            'codigo_pedido_externo': pedido.get('codigo_pedido_externo'),
            'origem': pedido.get('origem'),
            'status': {
                'id': pedido.get('situacao_pedido_id'),
                'nome': pedido.get('situacao_pedido', {}).get('nome') if pedido.get('situacao_pedido') else 'Pendente',
                'cor': pedido.get('situacao_pedido', {}).get('cor_status') if pedido.get('situacao_pedido') else '#f59e0b',
                'descricao': pedido.get('situacao_pedido', {}).get('descricao') if pedido.get('situacao_pedido') else ''
            },
            'cliente': {
                'nome': pedido.get('cliente_nome'),
                'documento': pedido.get('cliente_documento'),
                'telefone': pedido.get('cliente_telefone'),
                'email': pedido.get('cliente_email'),
                'informacoes_adicionais': pedido.get('informacoes_cliente', {})
            },
            'financeiro': {
                'total': float(pedido.get('total_pedido', 0)),
                'moeda': pedido.get('moeda', 'BRL'),
                'total_itens': total_itens,
                'total_quantidade': total_quantidade
            },
            'datas': {
                'venda': pedido.get('data_venda'),
                'criacao': pedido.get('created_at'),
                'atualizacao': pedido.get('updated_at'),
                'limite_envio': pedido.get('data_limite_envio')
            },
            'logistica': {
                'is_flex': pedido.get('is_flex', False),
                'servico_logistico': pedido.get('servico_logistico'),
                'canal_venda': {
                    'id': pedido.get('canal_venda_id'),
                    'nome': pedido.get('canal_venda', {}).get('nome') if pedido.get('canal_venda') else None,
                    'slug': pedido.get('canal_venda', {}).get('slug') if pedido.get('canal_venda') else None,
                    'cor': pedido.get('canal_venda', {}).get('color') if pedido.get('canal_venda') else '#007bff'
                }
            },
            'itens': pedido.get('itens_pedido', []),
            'integracoes': pedido.get('integracoes', []),
            'timeline': sorted(
                pedido.get('eventos', []),
                key=lambda x: x.get('created_at', ''),
                reverse=True
            )
        }
        
        # Buscar correlation_ids do pedido
        try:
            corr_response = supabase_db.table('entity_correlation_mapping')\
                .select('correlation_id')\
                .eq('entity_type', 'pedido')\
                .eq('entity_id', pedido_id)\
                .execute()
            
            correlation_ids = [c['correlation_id'] for c in corr_response.data or []]
            
            # Buscar task_execution_logs por correlation_id
            task_events = []
            if correlation_ids:
                tasks_response = supabase_db.table('task_execution_logs')\
                    .select('*')\
                    .in_('correlation_id', correlation_ids)\
                    .order('created_at', desc=True)\
                    .execute()
                
                # Converter para formato de timeline
                for task in tasks_response.data or []:
                    task_events.append({
                        'id': f'task-{task["id"]}',
                        'tipo': 'task',
                        'tipo_evento': f'TASK_{task["status"]}',
                        'descricao': f'Tarefa: {task["task_name"]}',
                        'created_at': task.get('started_at') or task.get('created_at'),
                        'metadata': {
                            'task_name': task['task_name'],
                            'task_type': task.get('task_type'),
                            'status': task['status'],
                            'error_message': task.get('error_message')
                        },
                        'correlation_id': task['correlation_id']
                    })
            
            # Mesclar com timeline existente
            timeline_completa = pedido.get('eventos', []) + task_events
            timeline_completa.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            resultado['timeline'] = timeline_completa
            
        except Exception as e:
            logger.error(f"Erro ao buscar tarefas por correlation_id: {e}")
            # Continuar sem task_events se houver erro
        
        return ApiResponse.success(data=resultado)
        
    except Exception as e:
        logger.error(f"Erro ao buscar pedido {pedido_id}: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao buscar detalhes do pedido: {str(e)}",
            status_code=500
        )


@pedidos_bp.route('/<int:pedido_id>/eventos', methods=['GET'])
@login_required
def get_pedido_eventos(pedido_id):
    """
    Retorna timeline de eventos de um pedido específico.
    """
    try:
        eventos_response = supabase_db.table('eventos_pedido').select('''
            *,
            pedido:pedidos(
                numero_pedido,
                codigo_pedido_externo
            )
        ''').eq('pedido_id', pedido_id).order('created_at', desc=True).execute()
        
        return ApiResponse.success(data=eventos_response.data)
        
    except Exception as e:
        logger.error(f"Erro ao buscar eventos do pedido {pedido_id}: {e}")
        return ApiResponse.error(
            message=f"Erro ao buscar eventos: {str(e)}",
            status_code=500
        )


@pedidos_bp.route('/<int:pedido_id>/status', methods=['PUT'])
@login_required
def update_pedido_status(pedido_id):
    """
    Atualiza o status de um pedido.
    
    Payload:
    {
        "situacao_pedido_id": 2,
        "observacoes": "Opcional"
    }
    """
    try:
        data = request.get_json()
        novo_status_id = data.get('situacao_pedido_id')
        observacoes = data.get('observacoes', '')
        
        if not novo_status_id:
            return ApiResponse.error(
                message="situacao_pedido_id é obrigatório",
                status_code=400
            )
        
        # Verificar se status existe
        status_response = supabase_db.table('situacoes_pedido').select('id, nome').eq('id', novo_status_id).execute()
        if not status_response.data:
            return ApiResponse.error(
                message=f"Status {novo_status_id} não encontrado",
                status_code=404
            )
        
        # Atualizar status
        update_response = supabase_db.table('pedidos').update({
            'situacao_pedido_id': novo_status_id,
            'updated_at': 'now()'
        }).eq('id', pedido_id).execute()
        
        if not update_response.data:
            return ApiResponse.error(
                message=f"Pedido {pedido_id} não encontrado",
                status_code=404
            )
        
        # Registrar evento de mudança de status
        pedido_atual = supabase_db.table('pedidos').select('situacao_pedido_id').eq('id', pedido_id).single().execute()
        
        if observacoes:
            order_service.register_event(
                pedido_id,
                'STATUS_CHANGED',
                f"Status alterado para {status_response.data[0]['nome']}. {observacoes}",
                payload={'novo_status_id': novo_status_id}
            )
        
        return ApiResponse.success(
            data={
                'pedido_id': pedido_id,
                'novo_status': status_response.data[0]
            },
            message="Status atualizado com sucesso"
        )
        
    except Exception as e:
        logger.error(f"Erro ao atualizar status do pedido {pedido_id}: {e}")
        return ApiResponse.error(
            message=f"Erro ao atualizar status: {str(e)}",
            status_code=500
        )


@pedidos_bp.route('/<int:pedido_id>/imprimir', methods=['POST'])
@login_required
def imprimir_pedido(pedido_id):
    """
    Gera dados formatados para impressão do pedido.
    Futuro: Gerar PDF.
    """
    try:
        # Reutiliza endpoint de detalhes
        detalhes_response = get_pedido_detalhe(pedido_id)
        
        if detalhes_response.status_code != 200:
            return detalhes_response
        
        dados = detalhes_response.get_json().get('data', {})
        
        # Formatar para impressão
        formato_impressao = {
            'pedido': {
                'numero': dados.get('numero_pedido'),
                'externo': dados.get('codigo_pedido_externo'),
                'data': dados.get('datas', {}).get('venda'),
                'status': dados.get('status', {}).get('nome')
            },
            'cliente': dados.get('cliente'),
            'itens': dados.get('itens'),
            'total': dados.get('financeiro', {}).get('total')
        }
        
        return ApiResponse.success(data=formato_impressao)
        
    except Exception as e:
        logger.error(f"Erro ao preparar impressão do pedido {pedido_id}: {e}")
        return ApiResponse.error(
            message=f"Erro ao preparar impressão: {str(e)}",
            status_code=500
        )


@pedidos_bp.route('/bulk-update-status', methods=['PUT'])
@login_required
def bulk_update_pedido_status():
    """
    Atualiza o status de múltiplos pedidos em massa.
    
    Payload:
    {
        "pedido_ids": [123, 456, 789],
        "situacao_pedido_id": 2,
        "observacoes": "Opcional"
    }
    """
    try:
        data = request.get_json()
        pedido_ids = data.get('pedido_ids', [])
        novo_status_id = data.get('situacao_pedido_id')
        observacoes = data.get('observacoes', '')
        
        if not pedido_ids:
            return ApiResponse.error(
                message="pedido_ids é obrigatório",
                status_code=400
            )
        
        if not novo_status_id:
            return ApiResponse.error(
                message="situacao_pedido_id é obrigatório",
                status_code=400
            )
        
        # Verificar se status existe
        status_response = supabase_db.table('situacoes_pedido').select('id, nome').eq('id', novo_status_id).execute()
        if not status_response.data:
            return ApiResponse.error(
                message=f"Status {novo_status_id} não encontrado",
                status_code=404
            )
        
        # Atualizar status em massa
        update_response = supabase_db.table('pedidos').update({
            'situacao_pedido_id': novo_status_id,
            'updated_at': 'now()'
        }).in_('id', pedido_ids).execute()
        
        if not update_response.data:
            return ApiResponse.error(
                message="Nenhum pedido encontrado para atualizar",
                status_code=404
            )
        
        # Registrar eventos de mudança de status para cada pedido
        status_nome = status_response.data[0]['nome']
        for pedido_id in pedido_ids:
            if observacoes:
                order_service.register_event(
                    pedido_id,
                    'STATUS_CHANGED',
                    f"Status alterado para {status_nome}. {observacoes}",
                    payload={'novo_status_id': novo_status_id}
                )
        
        return ApiResponse.success(
            data={
                'pedidos_atualizados': len(update_response.data),
                'novo_status': status_response.data[0]
            },
            message=f"{len(update_response.data)} pedido(s) atualizado(s) com sucesso"
        )
        
    except Exception as e:
        logger.error(f"Erro ao atualizar status em massa: {e}")
        return ApiResponse.error(
            message=f"Erro ao atualizar status: {str(e)}",
            status_code=500
        )


@pedidos_bp.route('/<int:pedido_id>/demandas', methods=['GET'])
@login_required
def get_pedido_demandas(pedido_id):
    """
    Retorna demandas vinculadas a um pedido específico.
    
    A relação é feita através da tabela pivot demandas_pedidos.
    """
    try:
        # Primeiro, buscar o pedido para obter o codigo_pedido_externo
        pedido_response = supabase_db.table('pedidos').select(
            'id, numero_pedido, codigo_pedido_externo'
        ).eq('id', pedido_id).single().execute()
        
        if not pedido_response.data:
            return ApiResponse.error(
                message=f"Pedido {pedido_id} não encontrado",
                status_code=404
            )
        
        pedido = pedido_response.data
        codigo_externo = pedido.get('codigo_pedido_externo')

        # Buscar demandas vinculadas via tabela pivot demandas_pedidos
        # Join: demandas_producao → demandas_pedidos (pivot)
        pivot_response = supabase_db.table('demandas_pedidos').select('''
            demanda_id,
            demandas_producao(
                id,
                demanda_id,
                descricao,
                status,
                data_entrega,
                horario_coleta,
                tipo_demanda,
                is_flex,
                created_at,
                canal_venda:canais_venda(nome),
                itens:itens_demanda(
                    id,
                    quantidade,
                    descricao,
                    sku,
                    finalizados_qtd
                )
            )
        ''').eq('pedido_id', pedido_id).execute()
        
        demandas = []
        if pivot_response.data:
            demandas = [item['demandas_producao'] for item in pivot_response.data if item.get('demandas_producao')]

        total_pedidos_por_demanda = {}
        demanda_ids = [demanda.get('id') for demanda in demandas if demanda.get('id')]
        if demanda_ids:
            vinculos_response = supabase_db.table('demandas_pedidos') \
                .select('demanda_id, pedido_id') \
                .in_('demanda_id', demanda_ids) \
                .execute()
            for vinculo in vinculos_response.data or []:
                demanda_id = vinculo.get('demanda_id')
                total_pedidos_por_demanda[demanda_id] = total_pedidos_por_demanda.get(demanda_id, 0) + 1
        
        # Formatando resposta
        demandas_formatadas = []
        for demanda in demandas:
            # Calcular progresso
            total_itens = len(demanda.get('itens', []))
            itens_finalizados = sum(
                float(item.get('finalizados_qtd', 0)) 
                for item in demanda.get('itens', [])
            )
            progresso = round((itens_finalizados / total_itens * 100)) if total_itens > 0 else 0
            
            demandas_formatadas.append({
                'id': demanda.get('id'),  # ID numérico para a rota
                'demanda_id': demanda.get('demanda_id'),  # UUID
                'descricao': demanda.get('descricao'),
                'status': demanda.get('status'),
                'data_entrega': demanda.get('data_entrega'),
                'horario_coleta': demanda.get('horario_coleta'),
                'tipo_demanda': demanda.get('tipo_demanda'),
                'is_flex': demanda.get('is_flex', False),
                'canal_venda': demanda.get('canal_venda'),
                'created_at': demanda.get('created_at'),
                'progresso': progresso,
                'total_itens': total_itens,
                'itens_finalizados': itens_finalizados,
                'qtd_pedidos_vinculados': total_pedidos_por_demanda.get(demanda.get('id'), 0)
            })
        
        return ApiResponse.success(data={
            'pedido_id': pedido_id,
            'numero_pedido': pedido.get('numero_pedido'),
            'codigo_externo': codigo_externo,
            'demandas': demandas_formatadas
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar demandas do pedido {pedido_id}: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(
            message=f"Erro ao buscar demandas: {str(e)}",
            status_code=500
        )
