"""
Endpoints para gerar demanda consolidada a partir de pedidos selecionados.

Usa a mesma lógica de consolidar.py/file_processors.py para agrupar produtos.
"""

from flask import request, Blueprint, jsonify
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.utils import apply_miolo_fixes
from utils.api_response import ApiResponse
import logging
from datetime import datetime

logger = logging.getLogger("DemandaConsolidada")

demanda_consolidada_bp = Blueprint('demanda_consolidada', __name__, url_prefix='/api/v2/pedidos')


@demanda_consolidada_bp.route('/gerar-demanda-consolidada', methods=['POST'])
@login_required
def gerar_demanda_consolidada():
    """
    Gera UMA demanda consolidada a partir de múltiplos pedidos selecionados.
    
    Lógica (mesma de file_processors.py):
    1. Busca todos os pedidos selecionados com itens
    2. Agrupa itens por produto/SKU (soma quantidades)
    3. Identifica miolo via BOM (mesma lógica de file_processors)
    4. Cria UMA demanda com itens consolidados
    
    Payload:
    {
        "pedido_ids": [123, 456, 789],
        "nome_demanda": "Demanda Consolidada - Shopee",
        "data_entrega": "2026-04-15",
        "horario_coleta": "14:00",
        "observacoes": "Urgente",
        "canal_venda_id": 1
    }
    """
    try:
        data = request.get_json() or {}
        raw_pedido_ids = data.get('pedido_ids') or []
        pedido_ids = []
        for pedido_id in raw_pedido_ids:
            try:
                normalized_id = int(pedido_id)
            except (TypeError, ValueError):
                return ApiResponse.error(message=f'ID de pedido invalido: {pedido_id}', status_code=400)
            if normalized_id not in pedido_ids:
                pedido_ids.append(normalized_id)
        
        if not pedido_ids:
            return ApiResponse.error(message='Nenhum pedido selecionado', status_code=400)
        
        user_id = request.headers.get('X-User-Email', 'System')
        
        # 1. Buscar todos os pedidos selecionados com seus itens
        pedidos_result = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo,
            canal_venda_id,
            canal_venda:canais_venda(nome),
            itens_pedido:itens_pedido(
                id,
                sku_externo,
                descricao,
                quantidade,
                produto_id
            )
        ''').in_('id', pedido_ids).execute()
        
        if not pedidos_result.data:
            return ApiResponse.error(message='Pedidos não encontrados', status_code=404)
        
        # 2. Consolidar itens por produto/SKU (mesma lógica de file_processors.py)
        # Estrutura: {(produto_id, sku): {descricao, quantidade_total, pedidos_origem, miolo}}
        pedidos_by_id = {int(pedido['id']): pedido for pedido in pedidos_result.data}
        missing_ids = [pedido_id for pedido_id in pedido_ids if pedido_id not in pedidos_by_id]
        if missing_ids:
            return ApiResponse.error(
                message=f'Pedido(s) nao encontrado(s): {", ".join(map(str, missing_ids))}',
                status_code=404
            )

        canais = {
            pedido.get('canal_venda_id')
            for pedido in pedidos_result.data
            if pedido.get('canal_venda_id')
        }
        if not canais:
            return ApiResponse.error(message='Os pedidos selecionados nao possuem origem da venda.', status_code=400)
        if len(canais) > 1:
            return ApiResponse.error(message='Selecione pedidos de apenas uma origem da venda.', status_code=400)

        selected_canal_venda_id = next(iter(canais))
        requested_canal_venda_id = data.get('canal_venda_id')
        if requested_canal_venda_id and int(requested_canal_venda_id) != int(selected_canal_venda_id):
            return ApiResponse.error(
                message='A origem da venda informada nao corresponde aos pedidos selecionados.',
                status_code=400
            )

        pedidos_sem_itens = [
            pedido.get('numero_pedido') or pedido.get('codigo_pedido_externo') or str(pedido.get('id'))
            for pedido in pedidos_result.data
            if not pedido.get('itens_pedido')
        ]
        if pedidos_sem_itens:
            return ApiResponse.error(
                message=f'Pedido(s) sem itens para consolidar: {", ".join(pedidos_sem_itens)}',
                status_code=400
            )

        itens_consolidados_map = {}
        
        for pedido in pedidos_result.data:
            itens = pedido.get('itens_pedido', [])
            for item in itens:
                produto_id = item.get('produto_id')
                sku = item.get('sku_externo', 'UNKNOWN')
                key = (produto_id, sku)
                
                if key not in itens_consolidados_map:
                    itens_consolidados_map[key] = {
                        'produto_id': produto_id,
                        'sku': sku,
                        'descricao': item.get('descricao', ''),
                        'quantidade_total': 0,
                        'pedidos_origem': [],
                        'miolo_nome': None,
                        'id_produto_miolo': None,
                        'canal_venda_id': pedido.get('canal_venda_id')
                    }
                
                itens_consolidados_map[key]['quantidade_total'] += item.get('quantidade', 0)
                if pedido['id'] not in itens_consolidados_map[key]['pedidos_origem']:
                    itens_consolidados_map[key]['pedidos_origem'].append(pedido['id'])
        
        # 3. Para cada item consolidado, identificar miolo via BOM ou SKU (mesma lógica de file_processors.py)
        for key, item_consolidado in itens_consolidados_map.items():
            produto_id = item_consolidado['produto_id']
            sku = item_consolidado['sku']

            if produto_id:
                # Tentar encontrar miolo na BOM (igual file_processors.py)
                miolo_nome, id_produto_miolo = get_miolo_from_bom(produto_id)
                if miolo_nome:
                    item_consolidado['miolo_nome'] = miolo_nome
                    item_consolidado['id_produto_miolo'] = id_produto_miolo
                else:
                    # Fallback: usar parte do SKU como miolo (igual file_processors.py)
                    miolo_fallback = resolve_miolo_from_sku(sku)
                    item_consolidado['miolo_nome'] = miolo_fallback
                    item_consolidado['id_produto_miolo'] = None
            else:
                # Sem produto_id, usar fallback do SKU
                miolo_fallback = resolve_miolo_from_sku(sku)
                item_consolidado['miolo_nome'] = miolo_fallback
                item_consolidado['id_produto_miolo'] = None
        
        itens_consolidados = list(itens_consolidados_map.values())
        
        logger.info(f"Consolidados {len(pedido_ids)} pedidos em {len(itens_consolidados)} itens únicos")
        
        # 4. Preparar lista de itens para demanda (no formato que criar_demanda_direta espera)
        itens_demanda = []
        
        for item_consolidado in itens_consolidados:
            itens_demanda.append({
                'sku': item_consolidado['sku'],
                'descricao': item_consolidado['descricao'],
                'quantidade': item_consolidado['quantidade_total'],
                'produto_id': item_consolidado['produto_id'],
                'miolo_nome': item_consolidado['miolo_nome'],  # Backend espera este campo
                'miolo_name': item_consolidado['miolo_nome'],  # Alias para compatibilidade
                'id_produto_miolo': item_consolidado['id_produto_miolo']
            })
        
        if not itens_demanda:
            return ApiResponse.error(message='Nenhum item válido para criar demanda', status_code=400)

        # ========================================================================
        # NOVA ARQUITETURA: Calcular sugestões antes de criar demanda
        # ========================================================================
        from nistiprint_shared.services.demandas_sugestoes_service import DemandasSugestoesService
        
        sugestoes = None
        canal_venda_id = selected_canal_venda_id
        marketplace_integration_id = data.get('marketplace_integration_id')
        
        if canal_venda_id:
            try:
                data_entrega_str = data.get('data_entrega')
                data_entrega = None
                if data_entrega_str:
                    data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
                
                sugestoes = DemandasSugestoesService.calcular_sugestoes(
                    canal_venda_id=canal_venda_id,
                    marketplace_integration_id=marketplace_integration_id,
                    tipo_demanda='PLATAFORMA',
                    data_entrega=data_entrega
                )
                logger.info(f"Sugestões calculadas para canal {canal_venda_id}: {sugestoes}")
            except Exception as e:
                logger.warning(f"Erro ao calcular sugestões: {e}")
                sugestoes = None
        # ========================================================================

        nome_demanda = data.get('nome_demanda') or f"Demanda Consolidada - {datetime.now().strftime('%d/%m')}"
        
        # Usar horario_coleta do payload ou da sugestão
        horario_coleta = data.get('horario_coleta')
        if not horario_coleta and sugestoes:
            horario_coleta = sugestoes.get('horario_coleta')

        # 5. Criar demanda única consolidada
        nova_demanda = demanda_producao_service.criar_demanda_direta(
            nome_demanda=nome_demanda,
            canal_venda_id=canal_venda_id,
            data_entrega_str=data.get('data_entrega', datetime.now().strftime('%Y-%m-%d')),
            lista_de_itens=itens_demanda,
            horario_coleta_especifico=horario_coleta,
            observacoes=data.get('observacoes'),
            user_id=user_id,
            tipo_demanda='PLATAFORMA',
            status='EM_PRODUCAO',
            marketplace_integration_id=marketplace_integration_id
        )

        if not nova_demanda:
            return ApiResponse.error(message='Falha ao criar demanda', status_code=500)

        # 6. Vincular pedidos à demanda criada (tabela pivot demandas_pedidos)
        demanda_id = nova_demanda.get('id')
        vinculos_payload = [
            {
                'demanda_id': demanda_id,
                'pedido_id': pedido_id
            }
            for pedido_id in pedido_ids
        ]

        try:
            supabase_db.table('demandas_pedidos').upsert(
                vinculos_payload,
                on_conflict='demanda_id,pedido_id'
            ).execute()
        except Exception as e:
            logger.error(f"Erro ao vincular pedidos a demanda {demanda_id}: {e}", exc_info=True)
            try:
                supabase_db.table('demandas_producao').delete().eq('id', demanda_id).execute()
            except Exception:
                logger.warning("Nao foi possivel remover demanda sem rastreabilidade apos falha de vinculo.", exc_info=True)
            return ApiResponse.error(message='Falha ao registrar rastreabilidade dos pedidos.', status_code=500)

        vinculos_res = supabase_db.table('demandas_pedidos') \
            .select('pedido_id') \
            .eq('demanda_id', demanda_id) \
            .in_('pedido_id', pedido_ids) \
            .execute()
        vinculos = [row['pedido_id'] for row in (vinculos_res.data or [])]

        if len(set(vinculos)) != len(set(pedido_ids)):
            logger.error(
                "Rastreabilidade incompleta para demanda %s: vinculados=%s esperados=%s",
                demanda_id,
                vinculos,
                pedido_ids
            )
            try:
                supabase_db.table('demandas_producao').delete().eq('id', demanda_id).execute()
            except Exception:
                logger.warning("Nao foi possivel remover demanda com rastreabilidade incompleta.", exc_info=True)
            return ApiResponse.error(message='Rastreabilidade incompleta. A demanda nao foi criada.', status_code=500)

        logger.info(f"Demanda {demanda_id} criada com {len(itens_demanda)} itens consolidados")
        logger.info(f"Pedidos vinculados: {len(vinculos)} de {len(pedido_ids)}")

        return ApiResponse.success(data={
            'demanda_id': demanda_id,
            'demanda_uuid': nova_demanda.get('demanda_id'),
            'itens_consolidados': len(itens_demanda),
            'pedidos_vinculados': len(vinculos),
            'total_pedidos_origem': len(pedido_ids),
            'sugestoes': sugestoes,  # NOVA ARQUITETURA: Retornar sugestões
            'message': f'Demanda consolidada criada com {len(itens_demanda)} itens de {len(pedido_ids)} pedidos!'
        })
        
    except Exception as e:
        logger.error(f"Erro ao gerar demanda consolidada: {e}", exc_info=True)
        return ApiResponse.error(message=str(e), status_code=500)


def get_miolo_from_bom(product_id):
    """
    Tenta encontrar o componente 'Miolo' na BOM do produto.
    Mesma lógica de file_processors.py
    """
    try:
        miolo_cat_id = str(app_config_service.get_config('producao_miolos_category_id') or '6')
        
        components = product_service.get_bom_components(str(product_id))
        
        for comp in components or []:
            if str(comp.get('categoria_id')) == miolo_cat_id:
                return comp.get('name'), comp.get('id')
        
        return None, None
    except Exception as e:
        logging.error(f"Erro ao buscar miolo da BOM para produto {product_id}: {e}")
        return None, None


def resolve_miolo_from_sku(external_sku, default_slice=10):
    """
    Extrai o miolo do SKU e aplica correções (mesma lógica de file_processors.py).
    """
    if not isinstance(external_sku, str):
        miolo_raw = str(external_sku)[:default_slice] if external_sku else '-'
    else:
        miolo_raw = external_sku[:default_slice]
    
    # Aplicar correções de miolo (igual file_processors.py)
    miolo_corrigido = apply_miolo_fixes(miolo_raw)
    
    return miolo_corrigido
