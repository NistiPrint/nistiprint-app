import logging
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

        detalhe_disponivel = bool(payload.get('itens')) or bool(payload.get('contato'))
        if not detalhe_disponivel:
            raise RuntimeError(
                f"detalhe Bling indisponível para id={correlation['bling_id']} "
                f"(token possivelmente expirado em inst={bling_inst['id']}); "
                f"reenfileirando para reprocesso"
            )

        # 2. UPSERT pedidos_bling (espelho do payload)
        pedido_bling_id = _upsert_pedido_bling(payload, bling_inst['id'])
        logger.info("[ingest] pedidos_bling upserted id=%s", pedido_bling_id)

        # 3. Resolver instância marketplace pela loja_id
        loja_id = str(payload.get('loja', {}).get('id') or '')
        marketplace_inst, pedido_shopee_id, shopee_data = None, None, None
        if loja_id:
            try:
                marketplace_inst = _resolve_marketplace_instance(loja_id, bling_inst['id'])
            except Exception as e:
                logger.warning(
                    "[ingest] falha ao resolver marketplace para loja_id=%s: %s — seguindo só com dados do Bling",
                    loja_id, e, exc_info=True,
                )
                marketplace_inst = None

            if marketplace_inst:
                correlation['marketplace_inst'] = marketplace_inst['id']
                logger.info("[ingest] marketplace resolved id=%s plataforma=%s nome=%s",
                            marketplace_inst['id'],
                            marketplace_inst.get('plataforma_slug'),
                            marketplace_inst.get('instance_name'))

                # 4. Enriquecimento via API marketplace (apenas Shopee no MVP)
                if marketplace_inst.get('plataforma_slug') == 'shopee':
                    try:
                        shopee_data = _fetch_shopee_detail(
                            marketplace_inst,
                            payload.get('numeroLoja'),
                        )
                        if shopee_data and not shopee_data.get('error'):
                            pedido_shopee_id = _upsert_pedido_shopee(
                                shopee_data,
                                marketplace_integration_id=marketplace_inst['id'],
                            )
                        else:
                            logger.warning(
                                "[ingest] enriquecimento Shopee retornou erro para order_sn=%s: %s — seguindo só com dados do Bling",
                                payload.get('numeroLoja'),
                                (shopee_data or {}).get('error'),
                            )
                            shopee_data = None
                            pedido_shopee_id = None
                    except Exception as e:
                        logger.warning(
                            "[ingest] enriquecimento Shopee falhou para order_sn=%s: %s — seguindo só com dados do Bling",
                            payload.get('numeroLoja'),
                            e,
                            exc_info=True,
                        )
                        shopee_data, pedido_shopee_id = None, None
            else:
                logger.warning("[ingest] loja_id=%s sem instância marketplace mapeada", loja_id)

        # 5. Resolver canal_venda_id pela channel_connection ativa
        canal_venda_id = _resolve_canal_venda_id(
            (marketplace_inst or {}).get('id'),
            bling_inst['id'],
            loja_id
        )

        # 6. Classificar Flex
        flex = flex_classifier_service.classify(
            supabase_db,
            fields={
                'servico_logistico': _volume_servico(payload),
                'shipping_carrier':  _resolve_shipping_carrier(
                    shopee_data,
                    payload.get('numeroLoja'),
                ),
                'fulfillment_flag':  (shopee_data or {}).get('fulfillment_flag'),
            },
            marketplace_integration_id=(marketplace_inst or {}).get('id'),
            log_context=correlation,
        )

        # 7. UPSERT pedidos
        pedido_id = _upsert_pedido_master(
            payload,
            pedido_bling_id=pedido_bling_id,
            pedido_shopee_id=pedido_shopee_id,
            bling_integration_id=bling_inst['id'],
            marketplace_integration_id=(marketplace_inst or {}).get('id'),
            canal_venda_id=canal_venda_id,
            is_flex=flex.is_flex,
            modalidade=flex.modalidade,
            shopee_data=shopee_data,
        )
        logger.info("[ingest] pedido upserted id=%s is_flex=%s modalidade=%s",
                    pedido_id, flex.is_flex, flex.modalidade)

        # 7.5. Detectar e marcar pedido como personalizado
        try:
            _detect_and_mark_personalized(payload, pedido_id)
        except Exception as e:
            logger.warning(
                "[ingest] detecção de personalizado falhou pedido_id=%s: %s",
                pedido_id, e, exc_info=True,
            )

        # 8. Auditoria
        _log_ingest(
            pedido_id=pedido_id,
            bling_id=correlation['bling_id'],
            marketplace_integration_id=(marketplace_inst or {}).get('id'),
            is_flex=flex.is_flex,
            flex_motivo=flex.motivo,
            matched_rule_id=flex.matched_rule_id if hasattr(flex, 'matched_rule_id') else None,
            raw_decision=flex.raw_decision if hasattr(flex, 'raw_decision') else None,
        )

        # 9. Encadear demanda
        demanda_producao_service.create_from_order(
            {'pedido_id': pedido_id, 'numeroLoja': payload.get('numeroLoja')},
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
    if not bling_order_id:
        logger.warning("[ingest] sem id para fetch detalhe Bling (inst=%s)", bling_inst.get('id'))
        return None
    try:
        from nistiprint_shared.services.bling.bling_client import BlingClient

        client = BlingClient.create_client_for_integration_id(int(bling_inst['id']))
        return client.get_order(bling_order_id)
    except Exception as e:
        logger.error(
            "[ingest] falha fetch detalhe Bling id=%s inst=%s: %s",
            bling_order_id,
            bling_inst.get('id'),
            e,
            exc_info=True,
        )
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


def _resolve_canal_venda_id(marketplace_integration_id, bling_integration_id, loja_id):
    """
    Resolve canal_venda_id pela channel_connection ativa.
    Fallback para canais_venda legado se necessário.
    """
    if not marketplace_integration_id:
        return None

    try:
        # Buscar channel_connection ativa
        cc = supabase_db.table('channel_connections') \
            .select('channel_id') \
            .eq('marketplace_integration_id', marketplace_integration_id) \
            .eq('is_active', True) \
            .limit(1).execute().data
        if cc:
            return cc[0].get('channel_id')

        # Fallback: buscar na tabela canais_venda (legado)
        if loja_id:
            cv = supabase_db.table('canais_venda') \
                .select('id') \
                .eq('conta_bling_id', str(loja_id)) \
                .limit(1).execute().data
            if cv:
                return cv[0].get('id')
    except Exception as e:
        logger.warning("[ingest] Erro ao resolver canal_venda_id: %s", e)

    return None


def _log_ingest(pedido_id, bling_id, marketplace_integration_id,
                is_flex, flex_motivo, matched_rule_id, raw_decision):
    """Grava auditoria do ingest na tabela pedido_ingest_log."""
    try:
        supabase_db.table('pedido_ingest_log').insert({
            'pedido_id': pedido_id,
            'bling_id': bling_id,
            'marketplace_integration_id': marketplace_integration_id,
            'is_flex': is_flex,
            'flex_motivo': flex_motivo,
            'matched_rule_id': matched_rule_id,
            'raw_decision': raw_decision,
        }).execute()
    except Exception as e:
        logger.warning("[ingest] Erro ao gravar auditoria: %s", e)

def _detect_and_mark_personalized(payload: dict, pedido_id: int | None = None):
    """
    Reaplica a regra de personalizado do fluxo legado.

    O identificador já atualiza pedidos/itens unificados e os espelhos legados,
    então aqui basta disparar o processamento e registrar falhas sem quebrar o ingest.
    """
    from nistiprint_shared.services.personalized_order_identifier import (
        personalized_order_identifier,
    )

    result = personalized_order_identifier.process_order(payload)
    if not result.get('success'):
        logger.warning(
            "[ingest] detector de personalizado retornou falha para pedido=%s: %s",
            pedido_id or payload.get('numeroLoja') or payload.get('numero'),
            result.get('error'),
        )
        return

    personalized_items = result.get('personalized_items') or []
    if personalized_items:
        logger.info(
            "[ingest] pedido=%s marcado como personalizado (%d itens)",
            pedido_id or payload.get('numeroLoja') or payload.get('numero'),
            len(personalized_items),
        )

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

def _resolve_shipping_carrier(shopee_data, numero_loja):
    """
    Resolve o shipping_carrier preferindo o enrichment atual e caindo para o
    espelho persistido em pedidos_shopee quando necessário.
    """
    if shopee_data:
        carrier = shopee_data.get('shipping_carrier')
        if carrier:
            return carrier

        for package in shopee_data.get('package_list') or []:
            carrier = package.get('shipping_carrier')
            if carrier:
                return carrier

    if not numero_loja:
        return None

    try:
        rows = supabase_db.table('pedidos_shopee') \
            .select('shipping_carrier, package_list') \
            .eq('codigo_pedido', str(numero_loja)) \
            .limit(1) \
            .execute() \
            .data

        if rows:
            row = rows[0]
            if row.get('shipping_carrier'):
                return row['shipping_carrier']

            for package in row.get('package_list') or []:
                carrier = package.get('shipping_carrier')
                if carrier:
                    return carrier
    except Exception as e:
        logger.warning(
            "[ingest] falha ao resolver shipping_carrier fallback para order_sn=%s: %s",
            numero_loja, e, exc_info=True,
        )

    return None

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

def _upsert_pedido_master(payload, *,
                         pedido_bling_id, pedido_shopee_id,
                         bling_integration_id, marketplace_integration_id,
                         canal_venda_id,           # derivado de channel_connections
                         is_flex, modalidade,
                         shopee_data,              # dict ou None
                         ):
    """
    Upsert pedido na tabela pedidos (tabela unificada).
    Popula TODOS os campos que a tela precisa exibir.

    Mapeamento de campos:
    - Bling numeroLoja = Marketplace order code (ex: Shopee order_sn)
    - No banco: codigo_pedido_externo (equivale a numeroLoja/order_sn)
    - Bling numero = Número interno do pedido no Bling
    - No banco: numero_pedido
    """
    # Identificadores
    bling_id      = payload.get('id')                          # ID interno Bling
    bling_numero  = str(payload.get('numero') or '')           # número exibido
    numero_loja   = payload.get('numeroLoja')                  # ID marketplace
    codigo_externo = numero_loja if numero_loja else f"BLING-{bling_id}"

    # Cliente (sempre do Bling — fonte canônica)
    contato = payload.get('contato') or {}

    # Datas
    data_venda          = _clean_date(payload.get('data'))
    data_limite_envio   = _clean_date(
        (shopee_data or {}).get('ship_by_date')
        or payload.get('dataPrevista')
    )

    # Logística
    transporte = payload.get('transporte') or {}
    volumes    = transporte.get('volumes') or []
    servico    = volumes[0].get('servico') if volumes else None

    # Status interno
    situacao_pedido_id = _resolve_situacao_interna(
        bling_integration_id,
        payload.get('situacao', {}).get('id'),
    )

    data = {
        'numero_pedido':              bling_numero,        # NÃO é unique
        'codigo_pedido_externo':      codigo_externo,      # UNIQUE
        'origem':                     'BLING',
        'pedido_bling_id':            pedido_bling_id,
        'pedido_shopee_id':           pedido_shopee_id,
        'bling_integration_id':       bling_integration_id,
        'marketplace_integration_id': marketplace_integration_id,
        'canal_venda_id':             canal_venda_id,
        'situacao_pedido_id':         situacao_pedido_id,
        'status_original':            str(payload.get('situacao', {}).get('id') or ''),

        # Cliente
        'cliente_nome':               contato.get('nome'),
        'cliente_documento':          contato.get('numeroDocumento'),
        'cliente_telefone':           contato.get('telefone') or contato.get('celular'),
        'cliente_email':              contato.get('email'),
        'informacoes_cliente':        contato or None,     # JSONB completo

        # Financeiro
        'total_pedido':               _safe_float(payload.get('total')),
        'moeda':                      'BRL',

        # Datas
        'data_venda':                 data_venda,
        'data_limite_envio':          data_limite_envio,

        # Logística / Flex
        'servico_logistico':          servico,
        'is_flex':                    is_flex,
        'modalidade_logistica':       modalidade,

        # Marketplace (preenchido só se houver enriquecimento)
        'buyer_username':             (shopee_data or {}).get('buyer_username'),
        'shipping_carrier':           (shopee_data or {}).get('shipping_carrier'),
        'message_to_seller':          (shopee_data or {}).get('raw', {}).get('message_to_seller'),

        'updated_at':                 datetime.now(timezone.utc).isoformat(),
    }

    # filtra None para não sobrescrever em update
    data = {k: v for k, v in data.items() if v is not None}

    res = supabase_db.table('pedidos').upsert(
        data, on_conflict='codigo_pedido_externo'
    ).execute()
    pedido_id = res.data[0]['id'] if res.data else None
    logger.info("[upsert_pedido_master] Pedido upserted: codigo_externo=%s, pedido_id=%s", codigo_externo, pedido_id)

    # Upsert itens do pedido
    if pedido_id:
        _upsert_itens_pedido(pedido_id, payload.get('itens', []))

    return pedido_id


def _clean_date(date_str):
    """Valida e limpa strings de data para evitar erros no Postgres."""
    if not date_str or not isinstance(date_str, str):
        return None
    if date_str.startswith('0000') or '0000-00-00' in date_str:
        return None
    return date_str


def _safe_float(value, default=0.0):
    """Converte valores de forma segura."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ['valor', 'total', 'quantidade']:
            if k in value:
                return _safe_float(value[k], default)
        return default
    try:
        return float(str(value).replace(',', '.'))
    except:
        return default


def _resolve_situacao_interna(bling_integration_id, bling_situacao_id):
    """Mapeia status do Bling para status interno via integration_status_mappings."""
    if not bling_situacao_id:
        return None
    mapping_res = supabase_db.table('integration_status_mappings') \
        .select('internal_situacao_pedido_id') \
        .eq('module_id', 'bling') \
        .eq('external_status_id', str(bling_situacao_id)) \
        .maybe_single().execute()
    return mapping_res.data['internal_situacao_pedido_id'] if mapping_res.data else None

def _volume_servico(payload):
    volumes = payload.get('transporte', {}).get('volumes', [])
    return volumes[0].get('servico') if volumes else None

def _upsert_itens_pedido(pedido_id, itens_bling):
    """
    Upsert itens do pedido na tabela itens_pedido.
    Usa vinculos_bling (o cadastro real de mapeamento) em vez de produtos.sku.
    """
    if not pedido_id or not itens_bling:
        return

    # Deletar itens existentes deste pedido para evitar duplicatas
    supabase_db.table('itens_pedido').delete().eq('pedido_id', pedido_id).execute()

    rows = []
    for it in itens_bling:
        codigo = it.get('codigo')                          # SKU vendido
        produto_bling_id = (it.get('produto') or {}).get('id')
        produto_id = _resolve_produto_interno(codigo, produto_bling_id)
        rows.append({
            'pedido_id':       pedido_id,
            'produto_id':      produto_id,
            'sku_externo':     codigo,
            'descricao':       it.get('descricao'),
            'quantidade':      _safe_float(it.get('quantidade'), 1.0),
            'preco_unitario':  _safe_float(it.get('valor')),
            'subtotal':        _safe_float(it.get('valor')) * _safe_float(it.get('quantidade'), 1.0),
            'updated_at':      datetime.now(timezone.utc).isoformat(),
        })

    if rows:
        supabase_db.table('itens_pedido').insert(rows).execute()
        logger.info("[upsert_itens_pedido] %d itens inseridos para pedido_id=%s", len(rows), pedido_id)


def _resolve_produto_interno(codigo, produto_bling_id):
    """
    Resolve o produto interno usando vinculos_bling.
    Prioridade: 1) vinculos_bling por bling_id, 2) vinculos_bling por SKU, 3) produtos.sku
    """
    # 1ª tentativa: vinculos_bling por bling_id
    if produto_bling_id:
        v = (supabase_db.table('vinculos_bling')
             .select('produto_id')
             .eq('codigo_bling', str(produto_bling_id))
             .limit(1).execute().data)
        if v:
            return v[0]['produto_id']

    # 2ª tentativa: vinculos_bling por SKU
    if codigo:
        v = (supabase_db.table('vinculos_bling')
             .select('produto_id')
             .eq('codigo_bling', str(codigo))
             .limit(1).execute().data)
        if v:
            return v[0]['produto_id']

    # 3ª tentativa: produtos por SKU
    if codigo:
        p = (supabase_db.table('produtos')
             .select('id')
             .eq('sku', codigo)
             .limit(1).execute().data)
        if p:
            return p[0]['id']

    return None


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
