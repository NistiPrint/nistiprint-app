import logging
from celery import shared_task
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service

logger = logging.getLogger(__name__)

BLING_BATCH_SIZE = 100

def agendar_sync_status_batch(pedido_ids, bling_integration_id=None):
    """Cria o registro do lote e agenda a task Celery
    
    Args:
        pedido_ids: Lista de IDs dos pedidos
        bling_integration_id: ID opcional da integração Bling específica
    """
    res = supabase_db.table('sync_status_batches').insert({
        'pedido_ids': pedido_ids,
        'total': len(pedido_ids),
        'status': 'PENDENTE',
    }).execute()
    
    if res.data:
        batch_id = res.data[0]['id']
        sync_status_batch_task.delay(batch_id, bling_integration_id)
        return batch_id
    return None

@shared_task(name='services.bling_status_sync.sync_batch', bind=True, max_retries=2)
def sync_status_batch_task(self, batch_id: str, bling_integration_id=None):
    """Task Celery para processar o lote de sincronização de status
    
    Args:
        batch_id: ID do batch de sincronização
        bling_integration_id: ID opcional da integração Bling específica
    """
    supabase_db.table('sync_status_batches').update({'status': 'RODANDO'}).eq('id', batch_id).execute()
    
    batch_res = supabase_db.table('sync_status_batches').select('*').eq('id', batch_id).single().execute()
    if not batch_res.data:
        logger.error(f"Batch {batch_id} não encontrado.")
        return
        
    batch = batch_res.data
    ids = batch['pedido_ids']

    # Busca os pedidos com codigo_pedido_externo
    pedidos_res = supabase_db.table('pedidos') \
        .select('id, codigo_pedido_externo') \
        .in_('id', ids).execute()
    
    if not pedidos_res.data:
        logger.warning(f"Nenhum pedido válido encontrado para o batch {batch_id}")
        supabase_db.table('sync_status_batches').update({
            'status': 'CONCLUIDO', 'finalizado_em': 'now()'
        }).eq('id', batch_id).execute()
        return

    pedidos = pedidos_res.data

    # Filtrar apenas pedidos com codigo_pedido_externo
    pedidos_validos = [p for p in pedidos if p.get('codigo_pedido_externo')]
    
    if not pedidos_validos:
        logger.warning(f"Nenhum pedido com codigo_pedido_externo encontrado para o batch {batch_id}")
        supabase_db.table('sync_status_batches').update({
            'status': 'CONCLUIDO', 'finalizado_em': 'now()',
            'sucesso': 0, 'falha': len(pedidos)
        }).eq('id', batch_id).execute()
        return

    sucesso, falha = 0, 0
    
    # Obter token da conta Bling (específica ou padrão)
    if bling_integration_id:
        # Usa integração específica fornecida
        integracao_res = supabase_db.table('installed_integrations') \
            .select('access_token') \
            .eq('id', bling_integration_id) \
            .eq('module_id', 'bling') \
            .maybe_single().execute()
        
        if not integracao_res.data:
            logger.error(f"Integração Bling específica (ID {bling_integration_id}) não encontrada")
            supabase_db.table('sync_status_batches').update({
                'status': 'CONCLUIDO', 'finalizado_em': 'now()',
                'sucesso': 0, 'falha': len(pedidos_validos)
            }).eq('id', batch_id).execute()
            return
        
        token = integracao_res.data.get('access_token')
        if not token:
            logger.error(f"Integração Bling (ID {bling_integration_id}) não tem access_token")
            supabase_db.table('sync_status_batches').update({
                'status': 'CONCLUIDO', 'finalizado_em': 'now()',
                'sucesso': 0, 'falha': len(pedidos_validos)
            }).eq('id', batch_id).execute()
            return
    else:
        # Usa conta Bling padrão configurada
        from nistiprint_shared.services.app_config_service import app_config_service
        
        default_bling_account_id = app_config_service.get_config('default_bling_account_id')
        if not default_bling_account_id:
            logger.error("Nenhuma conta Bling padrão configurada")
            supabase_db.table('sync_status_batches').update({
                'status': 'CONCLUIDO', 'finalizado_em': 'now()',
                'sucesso': 0, 'falha': len(pedidos_validos)
            }).eq('id', batch_id).execute()
            return
        
        integracao_res = supabase_db.table('installed_integrations') \
            .select('access_token') \
            .eq('id', default_bling_account_id) \
            .eq('module_id', 'bling') \
            .maybe_single().execute()
        
        if not integracao_res.data:
            logger.error(f"Integração Bling padrão (ID {default_bling_account_id}) não encontrada")
            supabase_db.table('sync_status_batches').update({
                'status': 'CONCLUIDO', 'finalizado_em': 'now()',
                'sucesso': 0, 'falha': len(pedidos_validos)
            }).eq('id', batch_id).execute()
            return
        
        token = integracao_res.data.get('access_token')
        if not token:
            logger.error(f"Integração Bling padrão (ID {default_bling_account_id}) não tem access_token")
            supabase_db.table('sync_status_batches').update({
                'status': 'CONCLUIDO', 'finalizado_em': 'now()',
                'sucesso': 0, 'falha': len(pedidos_validos)
            }).eq('id', batch_id).execute()
            return
    
    # Criar cliente Bling (passa dict com access_token)
    client = BlingClient({'access_token': token})
    
    # Extrair codigos_pedido_externo (numerosLoja)
    codigos_externos = [str(p['codigo_pedido_externo']) for p in pedidos_validos]
    
    # Buscar em lote usando get_orders_by_store_numbers
    bling_ids, bling_data, bling_id_numero, not_found = client.get_orders_by_store_numbers(codigos_externos)
    
    # Criar mapa de numeroLoja -> dados do pedido
    mapa_pedidos = {}
    for order in bling_data:
        numero_loja = order.get('numeroLoja')
        if numero_loja:
            mapa_pedidos[numero_loja] = order
    
    # Processar cada pedido
    for p in pedidos_validos:
        codigo_externo = str(p['codigo_pedido_externo'])
        pedido_id = p['id']
        
        if codigo_externo in not_found:
            logger.warning(f"Pedido {codigo_externo} não encontrado no Bling")
            supabase_db.table('sync_status_errors').insert({
                'batch_id': batch_id,
                'pedido_id': pedido_id,
                'bling_id': None,
                'erro': f'Pedido não encontrado no Bling: {codigo_externo}',
            }).execute()
            falha += 1
            continue
        
        # Encontrar dados do pedido no mapa
        detail = mapa_pedidos.get(codigo_externo)
        if not detail:
            logger.error(f"Pedido {codigo_externo} não encontrado no mapa de resultados")
            falha += 1
            continue
        
        bling_id = detail.get('id')
        
        # Atualizar status (já temos os dados completos)
        if _update_pedido_status(pedido_id, bling_id, detail):
            sucesso += 1
        else:
            falha += 1
        
        # Atualiza progresso parcialmente
        supabase_db.table('sync_status_batches').update({
            'sucesso': sucesso, 'falha': falha
        }).eq('id', batch_id).execute()
            
    supabase_db.table('sync_status_batches').update({
        'status': 'CONCLUIDO', 'finalizado_em': 'now()',
        'sucesso': sucesso, 'falha': falha
    }).eq('id', batch_id).execute()

def _update_pedido_status(pedido_id, bling_id, detail):
    """Atualiza o status do pedido no banco de dados
    
    Args:
        pedido_id: ID do pedido interno
        bling_id: ID do pedido no Bling
        detail: Objeto do pedido (já é o objeto direto, não response.get('data'))
    """
    try:
        situacao = detail.get('situacao', {})
        situacao_id = situacao.get('id')
        
        # 1. Atualiza ou cria registro em pedidos_bling
        pedidos_bling_res = supabase_db.table('pedidos_bling') \
            .select('id') \
            .eq('bling_id', bling_id) \
            .maybe_single().execute()
        
        if pedidos_bling_res.data:
            # Atualiza existente
            supabase_db.table('pedidos_bling').update({
                'situacao_id': situacao.get('id'),
                'situacao_valor': situacao.get('valor'),
                'bling_id': bling_id,
                'raw_payload': detail,
                'updated_at': 'now()'
            }).eq('bling_id', bling_id).execute()
        else:
            # Cria novo registro (caso não exista)
            supabase_db.table('pedidos_bling').insert({
                'bling_id': bling_id,
                'situacao_id': situacao.get('id'),
                'situacao_valor': situacao.get('valor'),
                'raw_payload': detail,
                'numero_pedido': detail.get('numero'),
                'numero_loja': detail.get('numeroLoja'),
            }).execute()

        # 2. Verifica origem do pedido antes de propagar status
        pedido_res = supabase_db.table('pedidos').select('origem').eq('id', pedido_id).maybe_single().execute()
        
        if pedido_res.data:
            origem = pedido_res.data.get('origem', '').upper()
            # Lista de marketplaces onde o status deve vir da plataforma, não do Bling
            marketplaces = ['SHOPEE', 'AMAZON', 'MERCADOLIVRE', 'SHEIN', 'TIKTOK']
            
            if origem in marketplaces:
                logger.info(f"Pedido {pedido_id} é de marketplace ({origem}), não propagando status do Bling")
                return True
        
        # 3. Propaga para pedidos via mapping integration_status_mappings
        mapping_res = supabase_db.table('integration_status_mappings') \
            .select('internal_situacao_pedido_id') \
            .eq('module_id', 'bling') \
            .eq('external_status_id', str(situacao_id)) \
            .maybe_single().execute()
        
        if mapping_res.data:
            supabase_db.table('pedidos').update({
                'situacao_pedido_id': mapping_res.data['internal_situacao_pedido_id'],
                'updated_at': 'now()'
            }).eq('id', pedido_id).execute()
            
        return True
    except Exception as e:
        logger.error(f"Erro ao atualizar pedido {pedido_id}: {e}")
        return False

def get_integrations_for_pedido(pedido_id):
    """
    Busca todas as integrações disponíveis para um pedido específico.
    
    Args:
        pedido_id: ID do pedido
        
    Returns:
        Lista de dicionários com integrações disponíveis (bling + marketplace)
    """
    try:
        # Buscar dados do pedido
        pedido_res = supabase_db.table('pedidos').select(
            'id, origem, canal_venda_id, shop_id_shopee'
        ).eq('id', pedido_id).maybe_single().execute()
        
        if not pedido_res.data:
            logger.warning(f"Pedido {pedido_id} não encontrado")
            return []
        
        pedido = pedido_res.data
        canal_venda_id = pedido.get('canal_venda_id')
        origem = pedido.get('origem')
        
        integracoes = []
        
        # 1. Buscar integrações via canal_venda_id (channel_connections)
        if canal_venda_id:
            config = integracao_canal_service.get_integration_by_canal(canal_venda_id)
            
            if config:
                # Adicionar integração Bling se disponível
                if config.get('bling_integration_id'):
                    bling_integracao = supabase_db.table('installed_integrations').select(
                        'id, module_id, instance_name, is_active'
                    ).eq('id', config['bling_integration_id']).eq('is_active', True).maybe_single().execute()
                    
                    if bling_integracao.data:
                        integracoes.append({
                            'id': bling_integracao.data['id'],
                            'module_id': bling_integracao.data['module_id'],
                            'instance_name': bling_integracao.data['instance_name'],
                            'type': 'erp'
                        })
                
                # Adicionar integração Marketplace se disponível
                if config.get('marketplace_integration_id'):
                    marketplace_integracao = supabase_db.table('installed_integrations').select(
                        'id, module_id, instance_name, is_active'
                    ).eq('id', config['marketplace_integration_id']).eq('is_active', True).maybe_single().execute()
                    
                    if marketplace_integracao.data:
                        integracoes.append({
                            'id': marketplace_integracao.data['id'],
                            'module_id': marketplace_integracao.data['module_id'],
                            'instance_name': marketplace_integracao.data['instance_name'],
                            'type': 'marketplace'
                        })
        
        # 2. Buscar integrações marketplace por shop_id (para Shopee, etc.)
        if origem and origem.lower() in ['shopee', 'amazon', 'mercadolivre', 'shein', 'tiktok']:
            shop_id = pedido.get('shop_id_shopee')
            if shop_id:
                # Buscar integrações do módulo que tenham este shop_id no config
                module_id = origem.lower()
                integracoes_res = supabase_db.table('installed_integrations').select(
                    'id, module_id, instance_name, is_active, config'
                ).eq('module_id', module_id).eq('is_active', True).execute()
                
                for integracao in integracoes_res.data or []:
                    config = integracao.get('config', {})
                    if config.get('shop_id') == shop_id:
                        # Verificar se já não foi adicionada
                        if not any(i['id'] == integracao['id'] for i in integracoes):
                            integracoes.append({
                                'id': integracao['id'],
                                'module_id': integracao['module_id'],
                                'instance_name': integracao['instance_name'],
                                'type': 'marketplace'
                            })
        
        return integracoes
        
    except Exception as e:
        logger.error(f"Erro ao buscar integrações para pedido {pedido_id}: {e}")
        return []

def get_available_integrations_for_pedidos(pedido_ids):
    """
    Busca a interseção de integrações disponíveis para múltiplos pedidos.
    
    Args:
        pedido_ids: Lista de IDs dos pedidos
        
    Returns:
        Lista de integrações comuns a todos os pedidos
    """
    if not pedido_ids:
        return []
    
    try:
        # Buscar integrações para cada pedido
        all_integrations = []
        for pedido_id in pedido_ids:
            integracoes = get_integrations_for_pedido(pedido_id)
            all_integrations.append(set((i['id'], i['module_id'], i['instance_name'], i['type']) for i in integracoes))
        
        if not all_integrations:
            return []
        
        # Calcular interseção
        common_integrations = set.intersection(*all_integrations)
        
        # Converter para formato de lista
        result = [
            {
                'id': item[0],
                'module_id': item[1],
                'instance_name': item[2],
                'type': item[3]
            }
            for item in common_integrations
        ]
        
        return result
        
    except Exception as e:
        logger.error(f"Erro ao buscar integrações comuns para pedidos {pedido_ids}: {e}")
        return []
