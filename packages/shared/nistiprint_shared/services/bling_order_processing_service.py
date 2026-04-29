import logging
import requests
from datetime import datetime, timezone
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services import flex_classifier_service
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver

logger = logging.getLogger("bling_order_processing")

def process_webhook(payload: dict, bling_integration_hint: int | None = None, company_id: str | None = None) -> dict:
    """
    Pipeline linear, idempotente.
    - payload: corpo do pedido Bling (já buscado da API com detalhes completos).
    - bling_integration_hint: quando o caller já sabe a instância Bling (ex.: webhook
      veio com header de identificação), evita lookup.
    - company_id: ID da empresa Bling do webhook wrapper (usado para resolver instância)
    """
    try:
        correlation = {
            'bling_id':    payload.get('id'),
            'numero':      payload.get('numero'),
            'numero_loja': payload.get('numeroLoja'),
        }
        logger.info("[ingest] start %s", correlation)

        # 1. Resolver instância Bling
        bling_inst = _resolve_bling_instance(payload, bling_integration_hint, company_id)
        correlation['bling_inst'] = bling_inst['id']
        logger.info("[ingest] bling_instance resolved id=%s cnpj=%s",
                    bling_inst['id'], bling_inst['config'].get('cnpj'))

        # 1.5. Buscar detalhe completo do pedido na API do Bling
        # O webhook é apenas um aviso de alteração, precisamos dos dados atualizados
        if payload.get('id'):
            detalhe = _fetch_bling_order_detail(bling_inst, payload['id'])
            if detalhe:
                payload = detalhe
                logger.info("[ingest] payload Bling atualizado via /pedidos/vendas/%s", payload.get('id'))
            else:
                logger.warning("[ingest] falha ao buscar detalhe Bling — pipeline continua com payload do webhook")

        # 2. UPSERT pedidos_bling (espelho do payload)
        pedido_bling_id = _upsert_pedido_bling(payload, bling_inst['id'])
        logger.info("[ingest] pedidos_bling upserted id=%s", pedido_bling_id)

        # 3. Resolver instância marketplace pela loja_id
        loja_id = str(payload.get('loja', {}).get('id') or '')
        marketplace_inst, pedido_shopee_id, shopee_data = None, None, None
        if loja_id:
            marketplace_inst = _resolve_marketplace_instance(loja_id, bling_inst['id'])
            if marketplace_inst:
                correlation['marketplace_inst'] = marketplace_inst['id']
                logger.info("[ingest] marketplace resolved id=%s plataforma=%s nome=%s",
                            marketplace_inst['id'],
                            marketplace_inst.get('plataforma_slug'),
                            marketplace_inst.get('instance_name'))

                # 4. Enriquecimento via API marketplace (apenas Shopee no MVP)
                if marketplace_inst.get('plataforma_slug') == 'shopee':
                    shopee_data = _fetch_shopee_detail(marketplace_inst,
                                                       payload.get('numeroLoja'))
                    pedido_shopee_id = _upsert_pedido_shopee(
                        shopee_data,
                        marketplace_integration_id=marketplace_inst['id'],
                    )
            else:
                logger.warning("[ingest] loja_id=%s sem instância marketplace mapeada", loja_id)

        # 5. Classificar Flex
        flex = flex_classifier_service.classify(
            supabase_db,
            fields={
                'servico_logistico': _volume_servico(payload),
                'shipping_carrier':  (shopee_data or {}).get('shipping_carrier'),
                'fulfillment_flag':  (shopee_data or {}).get('fulfillment_flag'),
            },
            marketplace_integration_id=(marketplace_inst or {}).get('id'),
            log_context=correlation,
        )

        # 6. UPSERT pedidos
        pedido_id = _upsert_pedido_master(
            payload,
            pedido_bling_id=pedido_bling_id,
            pedido_shopee_id=pedido_shopee_id,
            bling_integration_id=bling_inst['id'],
            marketplace_integration_id=(marketplace_inst or {}).get('id'),
            is_flex=flex.is_flex,
            modalidade=flex.modalidade,
        )
        logger.info("[ingest] pedido upserted id=%s is_flex=%s modalidade=%s",
                    pedido_id, flex.is_flex, flex.modalidade)

        # 7. Encadear demanda
        demanda_producao_service.create_from_order(
            {'pedido_id': pedido_id},
            is_flex=flex.is_flex,
            modalidade_logistica=flex.modalidade,
            marketplace_integration_id=(marketplace_inst or {}).get('id'),
        )

        logger.info("[ingest] done %s", correlation)
        return {
            'status': 'success',
            'pedido_id': pedido_id,
            'is_flex': flex.is_flex,
            'flex_motivo': flex.motivo
        }
    except Exception as e:
        logger.error("[ingest] Erro no processamento do webhook: %s", e, exc_info=True)
        return {
            'status': 'error',
            'message': str(e),
            'pedido_id': None
        }


# ---------- helpers ----------

def _fetch_bling_order_detail(bling_inst: dict, bling_order_id) -> dict | None:
    """Busca pedido detalhado no Bling. Retorna o objeto data ou None em falha.
    Token vem de credentials.access_token ou access_token na própria install."""
    cred = bling_inst.get('credentials') or {}
    token = bling_inst.get('access_token') or cred.get('access_token')
    if not token or not bling_order_id:
        logger.warning("[ingest] sem token/id para fetch detalhe Bling (inst=%s)", bling_inst.get('id'))
        return None
    url = f"https://api.bling.com.br/Api/v3/pedidos/vendas/{bling_order_id}"
    try:
        r = requests.get(url,
            headers={'Accept':'application/json','Authorization':f'Bearer {token}'},
            timeout=20)
        r.raise_for_status()
        return r.json().get('data')
    except requests.RequestException as e:
        logger.error("[ingest] falha fetch detalhe Bling id=%s: %s", bling_order_id, e)
        return None

def _resolve_bling_instance(payload, hint, company_id=None):
    if hint:
        row = supabase_db.table('installed_integrations') \
            .select('*').eq('id', hint).single().execute().data
        if row:
            return row
    
    # Try company_id first (from webhook wrapper)
    if company_id:
        rows = supabase_db.rpc('find_bling_integration_by_company_id',
                               {'p_company_id': company_id}).execute().data
        if rows:
            return rows[0]
    
    # Fallback to CNPJ from payload
    cnpj = (payload.get('intermediador') or {}).get('cnpj') \
        or (payload.get('loja') or {}).get('cnpj')
    if not cnpj:
        raise ValueError("Não foi possível identificar instância Bling: CNPJ ausente e company_id não fornecido")
    rows = supabase_db.rpc('find_bling_integration_by_cnpj',
                           {'p_cnpj': cnpj}).execute().data
    if not rows:
        raise LookupError(f"Nenhuma installed_integration Bling ativa para CNPJ={cnpj}")
    return rows[0]

def _resolve_marketplace_instance(loja_id: str, bling_integration_id: int | None = None):
    rows = supabase_db.rpc('find_marketplace_by_bling_loja',
                           {'p_loja_id': loja_id, 'p_bling_integration_id': bling_integration_id}).execute().data
    if not rows:
        return None
    inst = rows[0]
    # Anexar slug da plataforma para conveniência do caller
    mod = supabase_db.table('integration_modules') \
        .select('slug').eq('id', inst['module_id']).single().execute().data
    inst['plataforma_slug'] = (mod or {}).get('slug')
    return inst

def _fetch_shopee_detail(marketplace_inst, order_sn):
    cfg, cred = marketplace_inst['config'], marketplace_inst.get('credentials') or {}
    integration = {
        'config':       cfg,
        'credentials':  cred,
        'access_token': marketplace_inst.get('access_token') or cred.get('access_token'),
    }
    logger.info("[fetch_shopee_detail] Chamando driver com order_sn=%s, integration config keys=%s", order_sn, integration.keys())
    result = shopee_driver.get_order_detail(integration, [order_sn])
    logger.info("[fetch_shopee_detail] Resultado do driver: %s", result)
    return result

def _upsert_pedido_bling(payload, bling_integration_id):
    bling_id = payload.get('id')
    if not bling_id:
        return None
    
    data = {
        'bling_id': bling_id,
        'numero_pedido': str(payload.get('numero', '')),
        'numero_loja': payload.get('numeroLoja'),
        'situacao_id': payload.get('situacao', {}).get('id'),
        'situacao_valor': payload.get('situacao', {}).get('valor'),
        'contato': payload.get('contato'),
        'itens': payload.get('itens'),
        'transporte': payload.get('transporte'),
        'intermediador_cnpj': payload.get('intermediador', {}).get('cnpj'),
        'loja_id': payload.get('loja', {}).get('id'),
        'raw_payload': payload,
        'bling_integration_id': bling_integration_id,
        'updated_at': datetime.now(timezone.utc).isoformat()
    }
    
    res = supabase_db.table('pedidos_bling').upsert(data, on_conflict='bling_id').execute()
    return res.data[0]['id'] if res.data else None

def _upsert_pedido_shopee(shopee_data: dict, marketplace_integration_id: int) -> int:
    """
    Upsert pedido na tabela pedidos_shopee.

    Mapeamento de campos:
    - Shopee order_sn = Código do pedido na Shopee
    - No banco: codigo_pedido (equivale a order_sn, que também é o Bling numeroLoja)
    - Este campo é usado como chave única (on_conflict)
    """
    logger.info("[upsert_pedido_shopee] shopee_data keys: %s", shopee_data.keys() if shopee_data else None)
    logger.info("[upsert_pedido_shopee] shopee_data external_id: %s", shopee_data.get('external_id') if shopee_data else None)
    
    # Se shopee_data tiver 'error', significa que a chamada à API falhou
    if shopee_data and shopee_data.get('error'):
        logger.error("[upsert_pedido_shopee] Erro retornado pelo driver Shopee: %s", shopee_data.get('error'))
        raise ValueError(f"Erro ao buscar dados da Shopee: {shopee_data.get('error')}")
    
    row = {
        'codigo_pedido':     shopee_data.get('external_id'),  # order_sn (equivale a Bling numeroLoja)
        'shop_id':           shopee_data.get('shop_id'),
        'order_sn':          shopee_data.get('external_id'),
        'order_status':      shopee_data.get('order_status'),
        'buyer_username':    shopee_data.get('buyer_username'),
        'buyer_user_id':     shopee_data.get('buyer_user_id'),
        'fulfillment_flag':  shopee_data.get('fulfillment_flag'),
        'shipping_carrier':  shopee_data.get('shipping_carrier'),
        'package_list':      shopee_data.get('package_list'),
        'item_list':         shopee_data.get('item_list'),
        'recipient_address': shopee_data.get('recipient_address'),
        'pay_time':          shopee_data.get('pay_time'),
        'raw_payload':       shopee_data.get('raw'),
        'enriched_at':       'now()',
        'marketplace_integration_id': marketplace_integration_id,
    }
    
    if not row.get('codigo_pedido'):
        logger.error("[upsert_pedido_shopee] codigo_pedido está null - shopee_data: %s", shopee_data)
        raise ValueError("codigo_pedido (external_id) está null - não é possível upsert pedidos_shopee")
    
    res = supabase_db.table('pedidos_shopee') \
        .upsert(row, on_conflict='codigo_pedido').execute()
    return res.data[0]['id']

def _upsert_pedido_master(payload, **kwargs):
    """
    Upsert pedido na tabela pedidos (tabela unificada).
    
    Mapeamento de campos:
    - Bling numeroLoja = Marketplace order code (ex: Shopee order_sn)
    - No banco: codigo_pedido_externo (equivale a numeroLoja/order_sn)
    - Bling numero = Número interno do pedido no Bling
    - No banco: numero_pedido
    """
    bling_numero = str(payload.get('numero', ''))
    numero_loja = payload.get('numeroLoja')  # Equivale ao order_sn na Shopee
    codigo_externo = numero_loja if numero_loja else bling_numero  # codigo_pedido_externo
    
    data = {
        'codigo_pedido_externo': codigo_externo,
        'numero_pedido': bling_numero,
        'pedido_bling_id': kwargs.get('pedido_bling_id'),
        'pedido_shopee_id': kwargs.get('pedido_shopee_id'),
        'bling_integration_id': kwargs.get('bling_integration_id'),
        'marketplace_integration_id': kwargs.get('marketplace_integration_id'),
        'is_flex': kwargs.get('is_flex', False),
        'modalidade_logistica': kwargs.get('modalidade', 'STANDARD'),
        'cliente_nome': payload.get('contato', {}).get('nome'),
        'informacoes_cliente': payload.get('contato', {}),
        'data_venda': payload.get('data'),
        'origem': 'BLING',
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'personalizado': payload.get('has_personalized', False)
    }
    
    # Mapeamento de situação para situacao_pedido_id via integration_status_mappings
    situacao_id = payload.get('situacao', {}).get('id')
    if situacao_id:
        mapping_res = supabase_db.table('integration_status_mappings') \
            .select('internal_situacao_pedido_id') \
            .eq('module_id', 'bling') \
            .eq('external_status_id', str(situacao_id)) \
            .maybe_single().execute()
        if mapping_res.data:
            data['situacao_pedido_id'] = mapping_res.data['internal_situacao_pedido_id']

    try:
        res = supabase_db.table('pedidos').upsert(data, on_conflict='codigo_pedido_externo').execute()
        pedido_id = res.data[0]['id'] if res.data else None
        logger.info("[upsert_pedido_master] Pedido upserted: codigo_externo=%s, pedido_id=%s", codigo_externo, pedido_id)
        
        # Upsert itens do pedido
        if pedido_id:
            _upsert_itens_pedido(pedido_id, payload.get('itens', []))
        
        return pedido_id
    except Exception as e:
        logger.error("[upsert_pedido_master] Erro ao upsert pedido codigo_externo=%s: %s", codigo_externo, e, exc_info=True)
        raise

def _volume_servico(payload):
    volumes = payload.get('transporte', {}).get('volumes', [])
    return volumes[0].get('servico') if volumes else None

def _upsert_itens_pedido(pedido_id, itens_bling):
    """
    Upsert itens do pedido na tabela itens_pedido.
    Mapeia itens do Bling para a estrutura unificada.
    """
    logger.info("[upsert_itens_pedido] Iniciando - pedido_id=%s, itens_bling_count=%s", pedido_id, len(itens_bling) if itens_bling else 0)
    
    if not itens_bling:
        logger.warning("[upsert_itens_pedido] Nenhum item para upsert no pedido_id=%s - itens_bling está vazio ou None", pedido_id)
        return
    
    if not pedido_id:
        logger.error("[upsert_itens_pedido] pedido_id é None ou inválido - não é possível salvar itens")
        return
    
    try:
        # Primeiro deletar itens existentes deste pedido para evitar duplicatas
        logger.info("[upsert_itens_pedido] Deletando itens existentes do pedido_id=%s", pedido_id)
        delete_res = supabase_db.table('itens_pedido') \
            .delete() \
            .eq('pedido_id', pedido_id) \
            .execute()
        logger.info("[upsert_itens_pedido] Delete concluído para pedido_id=%s", pedido_id)
        
        # Inserir novos itens
        itens_to_insert = []
        for idx, item in enumerate(itens_bling):
            logger.debug("[upsert_itens_pedido] Processando item %d: codigo=%s, descricao=%s, valor=%s, quantidade=%s", 
                        idx, item.get('codigo'), item.get('descricao'), item.get('valor'), item.get('quantidade'))
            
            item_data = {
                'pedido_id': pedido_id,
                'sku_externo': item.get('codigo') or item.get('descricao'),
                'descricao': item.get('descricao'),
                'quantidade': float(item.get('quantidade', 0)),
                'preco_unitario': float(item.get('valor', 0)),
                'subtotal': float(item.get('valor', 0)) * float(item.get('quantidade', 0)),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            
            # Tentar encontrar produto correspondente pelo SKU externo
            if item.get('codigo'):
                produto_res = supabase_db.table('produtos') \
                    .select('id') \
                    .eq('sku', item.get('codigo')) \
                    .maybe_single().execute()
                if produto_res.data:
                    item_data['produto_id'] = produto_res.data['id']
                    logger.debug("[upsert_itens_pedido] Produto encontrado: produto_id=%s para sku=%s", produto_res.data['id'], item.get('codigo'))
            
            itens_to_insert.append(item_data)
        
        # Inserir todos os itens de uma vez
        if itens_to_insert:
            logger.info("[upsert_itens_pedido] Inserindo %d itens para pedido_id=%s", len(itens_to_insert), pedido_id)
            insert_res = supabase_db.table('itens_pedido').insert(itens_to_insert).execute()
            logger.info("[upsert_itens_pedido] %d itens upserted com sucesso para pedido_id=%s", len(itens_to_insert), pedido_id)
        else:
            logger.warning("[upsert_itens_pedido] itens_to_insert está vazio após processamento - nenhum item inserido")
    except Exception as e:
        logger.error("[upsert_itens_pedido] Erro ao upsert itens do pedido_id=%s: %s", pedido_id, e, exc_info=True)
        raise


def import_single_order_by_shop_id(shopee_order_sn: str):
    """
    Imports a single order from Bling based on the Shopee Order SN (numeroLoja).
    This is a manual import function that replicates the webhook processing logic.
    
    Args:
        shopee_order_sn: The Shopee order SN (numeroLoja) to import
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    from nistiprint_shared.services.bling.bling_client import BlingClient
    from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
    
    logger.info(f"[MANUAL_IMPORT] Starting import for order SN: {shopee_order_sn}")
    
    try:
        # 1. Get channel configuration by looking up the loja_id
        # First, we need to find which Bling integration has this order
        configs = integracao_canal_service.listar_configuracoes(include_inactive=False)
        
        if not configs:
            return False, "No active channel configurations found."
        
        # Try to find the order in each configured Bling integration
        found_order = None
        used_config = None
        
        for cfg in configs:
            bling_loja_id = cfg.get('bling_loja_id')
            if not bling_loja_id:
                continue
            
            try:
                bling_client = _bling_client_for_config(cfg)
                
                logger.info(f"[MANUAL_IMPORT] Checking config {cfg.get('id')} (bling_loja_id={bling_loja_id})")
                
                # Use get_orders_by_store_numbers to search by numeroLoja
                orders_found, orders_data, ids_with_numbers, not_found = bling_client.get_orders_by_store_numbers([shopee_order_sn])
                
                if orders_found > 0 and orders_data:
                    found_order = orders_data[0]  # Take the first match
                    used_config = cfg
                    logger.info(f"[MANUAL_IMPORT] Found order in config {cfg.get('id')}: bling_id={found_order.get('id')}")
                    break
                
            except Exception as e:
                logger.warning(f"[MANUAL_IMPORT] Error checking config {cfg.get('id')}: {e}")
                continue
        
        if not found_order:
            return False, f"Order {shopee_order_sn} not found in any configured Bling integration."
        
        # 2. Process the order through the standard pipeline
        result = process_webhook(found_order, bling_integration_hint=used_config.get('bling_integration_id'))
        
        pedido_id = result.get('pedido_id')
        if pedido_id:
            return True, f"Order {shopee_order_sn} imported successfully (pedido_id={pedido_id})"
        else:
            return False, f"Order {shopee_order_sn} processing failed."
            
    except Exception as e:
        logger.error(f"[MANUAL_IMPORT] Error importing order {shopee_order_sn}: {e}", exc_info=True)
        return False, f"Error importing order: {str(e)}"


def _bling_client_for_config(cfg):
    """Helper to create BlingClient from config (reused from pedidos_bling_import_service)"""
    from nistiprint_shared.services.bling.bling_client import BlingClient
    from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
    
    bling_iid = cfg.get("bling_integration_id")
    if bling_iid:
        return BlingClient.create_client_for_integration_id(int(bling_iid))
    
    plataforma_nome = cfg.get("plataforma_nome")
    canal_venda_id = cfg.get("canal_venda_id")
    
    if plataforma_nome:
        return BlingClient.create_client_for_platform(
            plataforma_nome.lower(),
            channel_id=canal_venda_id,
            function_name="ORDER_IMPORT",
        )
    
    if canal_venda_id:
        canal_info = integracao_canal_service.get_integration_by_canal(canal_venda_id, expected_module='bling')
        if canal_info and canal_info.get("plataforma_nome"):
            return BlingClient.create_client_for_platform(
                canal_info["plataforma_nome"].lower(),
                channel_id=canal_venda_id,
                function_name="ORDER_IMPORT",
            )
    
    logger.warning("Config without platform defined - using fallback shopee")
    return BlingClient.create_client_for_platform(
        "shopee",
        channel_id=canal_venda_id,
        function_name="ORDER_IMPORT",
    )
