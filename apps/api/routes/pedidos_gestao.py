"""
Endpoints para gestão unificada de pedidos.

Rotas:
    GET    /api/v2/pedidos/estatisticas         - Stats de pedidos
    POST   /api/v2/pedidos/importar             - Importar do Bling (API)
    POST   /api/v2/pedidos/upload-planilha      - Upload + processamento
    POST   /api/v2/pedidos/consolidar-selecionados - Consolidar selecionados
    POST   /api/v2/pedidos/gerar-demanda        - Gerar demanda em lote
    GET    /api/v2/pedidos/canais-proximos-coleta - Canais com coleta mais próxima
    GET    /api/v2/pedidos/contagem-por-canal   - Contagem de pedidos por canal
"""

from flask import request, Blueprint, jsonify
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.pedidos_bling_import_service import run_fetch_pedidos_em_andamento
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
from nistiprint_shared.services.integration_resolution_service import integration_resolution_service
from nistiprint_shared.services.celery_app import celery_app
from utils.api_response import ApiResponse
import logging
from datetime import datetime, timezone
import os
import json

logger = logging.getLogger("GestaoPedidos")

pedidos_gestao_bp = Blueprint('pedidos_gestao', __name__, url_prefix='/api/v2/pedidos')


@pedidos_gestao_bp.route('/estatisticas', methods=['GET'])
@login_required
def get_pedidos_estatisticas():
    """
    Retorna estatísticas de pedidos para dashboard.
    
    Query params:
    - canal_venda_id: Filtrar por canal (opcional)
    - dias: Período em dias (default: 30)
    """
    try:
        canal_venda_id = request.args.get('canal_venda_id', type=int)
        dias = request.args.get('dias', 30, type=int)
        
        # Calcular data inicial
        from datetime import timedelta
        data_inicio = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
        data_fim = datetime.now().strftime('%Y-%m-%d')
        
        # Query base para total de pedidos com retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                query = supabase_db.table('pedidos').select('id, situacao_pedido_id, canal_venda_id, canal_venda:canais_venda(nome)', count='exact')
                
                # Filtros
                if canal_venda_id:
                    query = query.eq('canal_venda_id', canal_venda_id)
                
                # Filtro de período
                query = query.gte('data_venda', data_inicio).lte('data_venda', data_fim)
                
                result = query.execute()
                break
            except Exception as e:
                if 'ConnectionTerminated' in str(e) and attempt < max_retries - 1:
                    logger.warning(f"Tentativa {attempt + 1} falhou, retrying...")
                    import time
                    time.sleep(1)
                else:
                    raise
        
        total_pedidos = result.count if hasattr(result, 'count') else len(result.data)

        # Estatísticas por status
        status_counts = {}
        for pedido in result.data:
            status = str(pedido.get('situacao_pedido_id', 'Unknown'))
            status_counts[status] = status_counts.get(status, 0) + 1

        # Contar pedidos COM DEMANDA (apenas situação 15 - Em Andamento)
        # Pedidos em outras situações não geram demanda
        pedidos_com_demanda = 0
        pedidos_com_demanda_ids = set()

        # Filtrar apenas pedidos em andamento (situação 15)
        pedidos_em_andamento_ids = [p['id'] for p in result.data if p.get('situacao_pedido_id') == 15]

        if pedidos_em_andamento_ids:
            for retry_attempt in range(max_retries):
                try:
                    demandas_pivot = supabase_db.table('demandas_pedidos').select('pedido_id').in_('pedido_id', pedidos_em_andamento_ids).execute()
                    pedidos_com_demanda_ids = set(p['pedido_id'] for p in demandas_pivot.data) if demandas_pivot.data else set()
                    pedidos_com_demanda = len(pedidos_com_demanda_ids)
                    break
                except Exception as e:
                    if 'ConnectionTerminated' in str(e) and retry_attempt < max_retries - 1:
                        logger.warning(f"Tentativa {retry_attempt + 1} de contar demandas falhou, retrying...")
                        import time
                        time.sleep(1)
                    else:
                        logger.error(f"Erro ao contar demandas: {e}")
                        break

        # Total de pedidos em andamento (para cálculo dos sem demanda)
        pedidos_em_andamento_total = len(pedidos_em_andamento_ids)
        pedidos_sem_demanda = pedidos_em_andamento_total - pedidos_com_demanda
        
        # Estatísticas por canal
        canais_stats = {}
        for pedido in result.data:
            canal_nome = pedido.get('canal_venda', {}).get('nome', 'Unknown') if pedido.get('canal_venda') else 'Unknown'
            canais_stats[canal_nome] = canais_stats.get(canal_nome, 0) + 1
        
        return ApiResponse.success(data={
            'total_pedidos': total_pedidos,
            'pedidos_com_demanda': pedidos_com_demanda,
            'pedidos_sem_demanda': pedidos_sem_demanda,
            'por_status': status_counts,
            'por_canal': canais_stats,
            'periodo': {
                'inicio': data_inicio,
                'fim': data_fim,
                'dias': dias
            }
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar estatísticas: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/canais-venda', methods=['GET'])
@login_required
def get_canais_venda():
    """
    Retorna lista de canais de venda disponíveis para filtros.
    Compatibilidade legada - retorna canais_venda.
    
    Query params:
    - ativos: true/false (default: true) - Filtrar apenas canais ativos
    """
    try:
        ativos = request.args.get('ativos', 'true').lower() in ('true', '1', 'yes')
        
        query = supabase_db.table('canais_venda').select('id, nome, slug, ativo')
        
        if ativos:
            query = query.eq('ativo', True)
        
        query = query.order('nome')
        
        result = query.execute()
        
        canais = result.data if result.data else []
        
        return ApiResponse.success(data={
            'canais': canais,
            'total': len(canais)
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar canais de venda: {e}")
        return ApiResponse.error(message=str(e), status_code=500)

@pedidos_gestao_bp.route('/marketplaces', methods=['GET'])
@login_required
def get_marketplaces():
    """
    Retorna lista de marketplaces disponíveis para filtros (nova arquitetura).
    Busca de installed_integrations com tipo marketplace.
    
    Query params:
    - ativos: true/false (default: true) - Filtrar apenas integrações ativas
    """
    try:
        ativos = request.args.get('ativos', 'true').lower() in ('true', '1', 'yes')
        marketplaces = integration_resolution_service.get_marketplace_options()
        if not ativos:
            pass
        else:
            marketplaces = [item for item in marketplaces if item.get('is_active', True)]
        
        return ApiResponse.success(data={
            'marketplaces': marketplaces,
            'total': len(marketplaces)
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar marketplaces: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/origens', methods=['GET'])
@login_required
def get_origens_pedidos():
    """
    Retorna origens realmente existentes para filtro de pedidos.

    Cada item usa key estavel: canal:<id>, marketplace:<id> ou bling_loja:<loja_id>.
    """
    try:
        result = supabase_db.rpc('get_pedidos_origem_options').execute()
        origens = result.data if result.data else []

        return ApiResponse.success(data={
            'origens': origens,
            'total': len(origens)
        })

    except Exception as e:
        logger.error(f"Erro ao buscar origens de pedidos: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/status-opcoes', methods=['GET'])
@login_required
def get_status_opcoes():
    """
    Retorna lista de status de pedidos disponíveis para filtros.
    """
    try:
        result = supabase_db.table('situacoes_pedido').select('id, nome, cor_status, descricao').order('id').execute()
        
        status = result.data if result.data else []
        
        return ApiResponse.success(data={
            'status': status,
            'total': len(status)
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar status de pedidos: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/importar', methods=['POST'])
@login_required
def importar_pedidos_bling():
    """
    Importa pedidos do Bling via API.
    
    Payload:
    {
        "config_id": "uuid-do-vinculo",  # Opcional, se não informado usa todos
        "dias": 7,                        # Opcional, se não houver datas
        "situacao_id": 15,                # Opcional, default: 15 (Em Andamento)
        "data_inicial": "2026-03-01",     # Opcional
        "data_final": "2026-03-30",       # Opcional
        "async": true                     # Opcional, default: true
    }
    """
    try:
        data = request.get_json() or {}
        config_id = data.get('config_id')
        dias = data.get('dias')
        
        # Aceita situacao_id ou id_situacao (para compatibilidade com exemplo do usuário)
        situacao_id = int(data.get('situacao_id') or data.get('id_situacao') or 15)
        
        # Aceita data_inicial ou dataInicial
        data_inicial = data.get('data_inicial') or data.get('dataInicial')
        data_final = data.get('data_final') or data.get('dataFinal')
        
        async_flag = data.get('async', True)
        
        if isinstance(async_flag, str):
            async_flag = async_flag.lower() in ('true', '1', 'yes')
        
        if async_flag:
            # Disparar task Celery
            task_kwargs = {
                'situacao_id': situacao_id,
            }
            
            if data_inicial and data_final:
                task_kwargs['data_inicial'] = data_inicial
                task_kwargs['data_final'] = data_final
            else:
                task_kwargs['dias'] = int(dias or 7)
            
            if config_id:
                task_kwargs['config_id'] = config_id
            
            celery_app.send_task(
                'tasks.pedidos_fetch_tasks.fetch_pedidos_em_andamento',
                kwargs=task_kwargs
            )
            
            msg = f'Importação enfileirada.'
            if data_inicial and data_final:
                msg += f' Período: {data_inicial} até {data_final}.'
            else:
                msg += f' Buscando pedidos dos últimos {dias or 7} dias.'

            return ApiResponse.success(data={
                'queued': True,
                'message': msg
            })
        
        # Execução síncrona
        result = run_fetch_pedidos_em_andamento(
            config_id=config_id,
            dias=int(dias or 7) if not (data_inicial and data_final) else None,
            situacao_id=situacao_id,
            data_inicial=data_inicial,
            data_final=data_final
        )
        
        return ApiResponse.success(data={
            'queued': False,
            'result': result
        })
        
    except Exception as e:
        logger.error(f"Erro ao importar pedidos: {e}", exc_info=True)
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/upload-planilha', methods=['POST'])
@login_required
def upload_planilha_pedidos():
    """
    Processa upload de planilha de pedidos (Shopee, ML, Amazon).
    Chama o endpoint /consolidar existente para manter consistência.
    """
    try:
        # Importar função consolidar diretamente
        from routes.consolidar import consolidar as consolidar_func
        
        # O request atual já tem os dados necessários, só chamar a função
        # O consolidar() vai ler de request.form e request.files diretamente
        return consolidar_func()
            
    except Exception as e:
        logger.error(f"Erro ao processar planilha: {e}", exc_info=True)
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/consolidar-selecionados', methods=['POST'])
@login_required
def consolidar_pedidos_selecionados():
    """
    Consolida pedidos selecionados para gerar demanda.
    
    Payload:
    {
        "pedido_ids": [123, 456, 789],  # IDs dos pedidos selecionados
        "agrupar_por": "produto"         # produto, sku, canal (opcional, default: produto)
    }
    
    Retorna:
    {
        "itens_consolidados": [
            {
                "produto_id": 123,
                "produto_nome": "Produto X",
                "sku": "ABC123",
                "quantidade": 10,
                "pedidos_origem": [123, 456]
            }
        ],
        "total_pedidos": 3,
        "total_itens": 2
    }
    """
    try:
        data = request.get_json() or {}
        pedido_ids = data.get('pedido_ids', [])
        agrupar_por = data.get('agrupar_por', 'produto')
        
        if not pedido_ids:
            return ApiResponse.error(message='Nenhum pedido selecionado', status_code=400)
        
        # Buscar pedidos selecionados
        pedidos_result = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo,
            canal_venda_id,
            canal_venda:canais_venda(nome),
            itens_pedido:itens_pedido(
                id,
                produto_id,
                sku_externo,
                descricao,
                quantidade
            )
        ''').in_('id', pedido_ids).execute()
        
        if not pedidos_result.data:
            return ApiResponse.error(message='Pedidos não encontrados', status_code=404)
        
        # Consolidar itens
        itens_consolidados_map = {}
        
        for pedido in pedidos_result.data:
            itens = pedido.get('itens_pedido', [])
            for item in itens:
                # Chave de agrupamento
                if agrupar_por == 'sku':
                    key = item.get('sku_externo', 'unknown')
                elif agrupar_por == 'canal':
                    key = f"{pedido.get('canal_venda_id')}_{item.get('sku_externo')}"
                else:  # produto
                    key = str(item.get('produto_id', 'unknown'))
                
                if key not in itens_consolidados_map:
                    itens_consolidados_map[key] = {
                        'produto_id': item.get('produto_id'),
                        'produto_nome': item.get('descricao', 'Unknown'),
                        'sku': item.get('sku_externo'),
                        'quantidade': 0,
                        'pedidos_origem': [],
                        'canal_venda_nome': pedido.get('canal_venda', {}).get('nome') if pedido.get('canal_venda') else None
                    }
                
                itens_consolidados_map[key]['quantidade'] += item.get('quantidade', 0)
                if pedido['id'] not in itens_consolidados_map[key]['pedidos_origem']:
                    itens_consolidados_map[key]['pedidos_origem'].append(pedido['id'])
        
        itens_consolidados = list(itens_consolidados_map.values())
        
        return ApiResponse.success(data={
            'itens_consolidados': itens_consolidados,
            'total_pedidos': len(pedidos_result.data),
            'total_itens': len(itens_consolidados),
            'agrupar_por': agrupar_por
        })
        
    except Exception as e:
        logger.error(f"Erro ao consolidar pedidos: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/gerar-demanda', methods=['POST'])
@login_required
def gerar_demanda_pedidos():
    """
    Gera demanda de produção a partir de pedidos selecionados ou itens consolidados.

    Payload (opção 1 - pedidos selecionados):
    {
        "pedido_ids": [123, 456],
        "nome_demanda": "Demanda Shopee - Março",
        "data_entrega": "2026-04-15",
        "horario_coleta": "14:00",  # Opcional: se não fornecido, usa sugestão
        "observacoes": "Urgente"
    }

    Payload (opção 2 - itens consolidados):
    {
        "itens": [
            {
                "produto_id": 123,
                "descricao": "Produto X",
                "sku": "ABC123",
                "quantidade": 10
            }
        ],
        "nome_demanda": "Demanda Consolidada",
        "data_entrega": "2026-04-15",
        "canal_venda_id": 1,
        "horario_coleta": "14:00",  # Opcional: se não fornecido, usa sugestão
        "observacoes": ""
    }
    
    Response inclui sugestões calculadas:
    {
        "success": true,
        "demandas_criadas": [...],
        "sugestoes": {
            "horario_coleta": "14:00",
            "modalidade_logistica": "STANDARD",
            ...
        }
    }
    """
    try:
        data = request.get_json() or {}
        user_id = request.headers.get('X-User-Email', 'System')

        # ========================================================================
        # NOVA ARQUITETURA: Calcular sugestões antes de criar demanda
        # ========================================================================
        from nistiprint_shared.services.demandas_sugestoes_service import DemandasSugestoesService
        
        sugestoes = None
        canal_venda_id_para_sugestao = None
        
        # Descobrir canal_venda_id para sugestões
        pedido_ids = data.get('pedido_ids')
        if pedido_ids and len(pedido_ids) > 0:
            # Buscar primeiro pedido para obter canal_venda_id
            primeiro_pedido = supabase_db.table('pedidos').select('canal_venda_id').eq('id', pedido_ids[0]).single().execute()
            if primeiro_pedido.data:
                canal_venda_id_para_sugestao = primeiro_pedido.data.get('canal_venda_id')
        else:
            canal_venda_id_para_sugestao = data.get('canal_venda_id')
        
        # Calcular sugestões se temos canal
        if canal_venda_id_para_sugestao:
            try:
                from datetime import datetime
                data_entrega_str = data.get('data_entrega')
                data_entrega = None
                if data_entrega_str:
                    data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
                
                sugestoes = DemandasSugestoesService.calcular_sugestoes(
                    canal_venda_id=canal_venda_id_para_sugestao,
                    tipo_demanda='PLATAFORMA',
                    data_entrega=data_entrega
                )
            except Exception as e:
                logger.warning(f"Erro ao calcular sugestões: {e}")
                sugestoes = None
        # ========================================================================

        # Opção 1: Gerar a partir de pedidos selecionados
        pedido_ids = data.get('pedido_ids')
        if pedido_ids:
            # Buscar pedidos e criar demanda automaticamente
            # Cada pedido gera sua própria demanda (ou consolidar se preferir)
            demandas_criadas = []

            for pedido_id in pedido_ids:
                # Buscar pedido completo
                pedido_result = supabase_db.table('pedidos').select('''
                    *,
                    itens_pedido:itens_pedido(
                        sku_externo,
                        descricao,
                        quantidade,
                        produto_id
                    )
                ''').eq('id', pedido_id).single().execute()

                if not pedido_result.data:
                    continue

                pedido = pedido_result.data

                # Preparar itens da demanda
                itens_demanda = []
                for item in pedido.get('itens_pedido', []):
                    itens_demanda.append({
                        'sku': item.get('sku_externo'),
                        'descricao': item.get('descricao'),
                        'quantidade': item.get('quantidade'),
                        'produto_id': item.get('produto_id')
                    })

                # Criar demanda
                nome_demanda = data.get('nome_demanda') or f"Pedido {pedido.get('numero_pedido', pedido_id)}"
                
                # Usar horario_coleta do payload ou da sugestão
                horario_coleta = data.get('horario_coleta')
                if not horario_coleta and sugestoes:
                    horario_coleta = sugestoes.get('horario_coleta')

                nova_demanda = demanda_producao_service.criar_demanda_direta(
                    nome_demanda=nome_demanda,
                    canal_venda_id=pedido.get('canal_venda_id'),
                    data_entrega_str=data.get('data_entrega', datetime.now().strftime('%Y-%m-%d')),
                    lista_de_itens=itens_demanda,
                    horario_coleta_especifico=horario_coleta,
                    observacoes=data.get('observacoes'),
                    user_id=user_id,
                    tipo_demanda='PLATAFORMA',
                    status='EM_PRODUCAO',
                    pedido_id=pedido_id
                )

                if nova_demanda:
                    demandas_criadas.append({
                        'pedido_id': pedido_id,
                        'demanda_id': nova_demanda.get('id'),
                        'demanda_uuid': nova_demanda.get('demanda_id')
                    })

            return ApiResponse.success(data={
                'demandas_criadas': demandas_criadas,
                'total': len(demandas_criadas),
                'sugestoes': sugestoes,  # NOVA ARQUITETURA: Retornar sugestões
                'message': f'{len(demandas_criadas)} demanda(s) criada(s) com sucesso!'
            })

        # Opção 2: Gerar a partir de itens consolidados
        itens = data.get('itens', [])
        if itens:
            canal_venda_id = data.get('canal_venda_id')
            if not canal_venda_id:
                return ApiResponse.error(message='canal_venda_id é obrigatório para itens consolidados', status_code=400)

            # Preparar lista de itens
            lista_itens = []
            for item in itens:
                lista_itens.append({
                    'sku': item.get('sku'),
                    'descricao': item.get('descricao', item.get('produto_nome')),
                    'quantidade': item.get('quantidade'),
                    'produto_id': item.get('produto_id')
                })

            # Criar demanda
            nome_demanda = data.get('nome_demanda') or f"Demanda Consolidada - {datetime.now().strftime('%d/%m')}"
            
            # Usar horario_coleta do payload ou da sugestão
            horario_coleta = data.get('horario_coleta')
            if not horario_coleta and sugestoes:
                horario_coleta = sugestoes.get('horario_coleta')

            nova_demanda = demanda_producao_service.criar_demanda_direta(
                nome_demanda=nome_demanda,
                canal_venda_id=canal_venda_id,
                data_entrega_str=data.get('data_entrega', datetime.now().strftime('%Y-%m-%d')),
                lista_de_itens=lista_itens,
                horario_coleta_especifico=horario_coleta,
                observacoes=data.get('observacoes'),
                user_id=user_id,
                tipo_demanda='PLATAFORMA',
                status='EM_PRODUCAO'
            )

            return ApiResponse.success(data={
                'demanda_id': nova_demanda.get('id'),
                'demanda_uuid': nova_demanda.get('demanda_id'),
                'sugestoes': sugestoes,  # NOVA ARQUITETURA: Retornar sugestões
                'message': 'Demanda consolidada criada com sucesso!'
            })

        return ApiResponse.error(message='Nenhum pedido_ids ou itens fornecidos', status_code=400)

    except Exception as e:
        logger.error(f"Erro ao gerar demanda: {e}", exc_info=True)
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/canais-proximos-coleta', methods=['GET'])
@login_required
def get_canais_proximos_coleta():
    """
    Retorna os 2 canais com horário de coleta mais próximo do horário atual.
    Usa a função SQL fn_canais_proximos_coleta().
    """
    try:
        from datetime import datetime

        logger.info("=== get_canais_proximos_coleta iniciado ===")

        # Primeiro, verificar se existem canais com horario_coleta
        canais_check = supabase_db.table('canais_venda').select('id, nome, horario_coleta, ativo').eq('ativo', True).not_.is_('horario_coleta', None).execute()
        logger.info(f"Canais ativos com horario_coleta: {len(canais_check.data) if canais_check.data else 0}")
        if canais_check.data:
            logger.info(f"Canais encontrados: {[(c['nome'], str(c['horario_coleta'])) for c in canais_check.data]}")

        # Chamar função SQL
        logger.info("Chamando fn_canais_proximos_coleta...")
        result = supabase_db.rpc('fn_canais_proximos_coleta', {'p_limit': 2}).execute()
        
        # Verificar erro no resultado do Supabase
        if hasattr(result, 'error') and result.error:
            logger.error(f"Erro na função SQL: {result.error}")
            return ApiResponse.error(message=f"Erro na função SQL: {result.error}", status_code=500)
        
        # Verificar se há exception no resultado
        if hasattr(result, 'exception') and result.exception:
            logger.error(f"Exception na função SQL: {result.exception}")
            return ApiResponse.error(message=f"Erro na função SQL: {result.exception}", status_code=500)

        canais_proximos = result.data if result.data else []
        logger.info(f"Canais próximos retornados: {len(canais_proximos)}")

        # Formatar dados
        canais_formatados = []
        for canal in canais_proximos:
            canais_formatados.append({
                'id': canal.get('fn_id'),
                'nome': canal.get('fn_nome'),
                'horario_coleta': canal.get('fn_horario_coleta', ''),  # Já vem formatado HH:MI
                'flex': canal.get('fn_flex', False),
                'fulfillment': canal.get('fn_fulfillment', False),
                'color': canal.get('fn_color'),
                'distancia_minutos': canal.get('fn_dist_min', 0),
                'is_proximo': canal.get('fn_is_proximo', True),
            })

        # Obter horário atual
        horario_atual = datetime.now().strftime('%H:%M')

        # Contar total de canais ativos
        total_canais = supabase_db.table('canais_venda').select('id', count='exact').eq('ativo', True).not_.is_('horario_coleta', None).execute()

        logger.info(f"=== get_canais_proximos_coleta concluído: {len(canais_formatados)} canais ===")

        return ApiResponse.success(data={
            'canais_proximos': canais_formatados,
            'horario_atual': horario_atual,
            'total_canais_ativos': total_canais.count if hasattr(total_canais, 'count') else 0
        })

    except Exception as e:
        logger.error(f"Erro ao buscar canais próximos: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)


@pedidos_gestao_bp.route('/contagem-por-canal', methods=['GET'])
@login_required
def get_contagem_pedidos_por_canal():
    """
    Retorna contagem de pedidos por canal de venda.
    Usa a função SQL fn_contar_pedidos_por_canal().

    Query params:
    - canal_venda_id: Filtrar por canal específico (opcional)
    - dias: Período em dias (default: 7)
    - has_demanda: true/false (opcional) - Filtrar por pedidos com/sem demanda
    """
    try:
        canal_venda_id = request.args.get('canal_venda_id', type=int)
        dias = request.args.get('dias', 7, type=int)
        has_demanda = request.args.get('has_demanda', type=str)

        # Converter has_demanda para boolean ou None
        if has_demanda:
            has_demanda = has_demanda.lower() in ('true', '1', 'yes')
        else:
            has_demanda = None

        # Chamar função SQL
        result = supabase_db.rpc('fn_contar_pedidos_por_canal', {
            'p_canal_venda_id': canal_venda_id,
            'p_dias': dias,
            'p_has_demanda': has_demanda
        }).execute()

        contagens = result.data if result.data else []

        # Formatar dados
        contagens_formatadas = []
        for contagem in contagens:
            contagens_formatadas.append({
                'canal_venda_id': contagem.get('canal_venda_id'),
                'canal_venda_nome': contagem.get('canal_venda_nome'),
                'total_pedidos': contagem.get('total_pedidos', 0),
                'pedidos_sem_demanda': contagem.get('pedidos_sem_demanda', 0),
                'pedidos_com_demanda': contagem.get('pedidos_com_demanda', 0),
            })

        return ApiResponse.success(data={
            'contagens': contagens_formatadas,
            'periodo_dias': dias,
            'filtro_canal': canal_venda_id,
            'filtro_demanda': has_demanda
        })

    except Exception as e:
        logger.error(f"Erro ao buscar contagem de pedidos: {e}")
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)
