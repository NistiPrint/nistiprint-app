-- Fix idempotent ERP/enrichment reference updates.
-- The canonical reference uniqueness is (pedido_id, integration_id, role), so
-- the RPC must target that index when the provider changes an external id.

CREATE OR REPLACE FUNCTION public.upsert_canonical_order(
  p_order JSONB,
  p_snapshot JSONB DEFAULT NULL,
  p_refs JSONB DEFAULT '[]'::jsonb
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
  v_pedido_id BIGINT;
  v_module_id TEXT := lower(NULLIF(p_order->>'marketplace_module_id', ''));
  v_marketplace_order_id TEXT := NULLIF(p_order->>'marketplace_order_id', '');
  v_ref JSONB;
BEGIN
  IF v_module_id IS NULL OR v_marketplace_order_id IS NULL THEN
    RAISE EXCEPTION
      'Canonical order identity is required (marketplace_module_id + marketplace_order_id)';
  END IF;

  INSERT INTO public.pedidos (
    marketplace_module_id, marketplace_order_id, marketplace_integration_id,
    ingest_source, erp_integration_id, erp_store_id, erp_order_id,
    erp_order_number, situacao_pedido_id, status_original, total_pedido,
    moeda, data_venda, cliente_nome, cliente_documento, cliente_telefone,
    cliente_email, is_flex, is_fulfillment, modalidade_logistica,
    servico_logistico, data_limite_envio, data_compra_marketplace,
    data_pagamento_marketplace, data_coleta, data_envio_marketplace,
    regra_logistica_integracao_id, personalizado, canal_venda_id,
    informacoes_cliente, pedido_bling_id, pedido_shopee_id,
    pedido_mercadolivre_id, buyer_username, shipping_carrier,
    message_to_seller, updated_at
  ) VALUES (
    v_module_id,
    v_marketplace_order_id,
    NULLIF(p_order->>'marketplace_integration_id', '')::INTEGER,
    NULLIF(p_order->>'ingest_source', ''),
    NULLIF(p_order->>'erp_integration_id', '')::INTEGER,
    NULLIF(p_order->>'erp_store_id', ''),
    NULLIF(p_order->>'erp_order_id', '')::BIGINT,
    NULLIF(p_order->>'erp_order_number', ''),
    NULLIF(p_order->>'situacao_pedido_id', '')::INTEGER,
    NULLIF(p_order->>'status_original', ''),
    NULLIF(p_order->>'total_pedido', '')::NUMERIC,
    COALESCE(NULLIF(p_order->>'moeda', ''), 'BRL'),
    NULLIF(p_order->>'data_venda', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'cliente_nome', ''),
    NULLIF(p_order->>'cliente_documento', ''),
    NULLIF(p_order->>'cliente_telefone', ''),
    NULLIF(p_order->>'cliente_email', ''),
    COALESCE((p_order->>'is_flex')::BOOLEAN, false),
    COALESCE((p_order->>'is_fulfillment')::BOOLEAN, false),
    NULLIF(p_order->>'modalidade_logistica', ''),
    NULLIF(p_order->>'servico_logistico', ''),
    NULLIF(p_order->>'data_limite_envio', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_compra_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_pagamento_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_coleta', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_envio_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'regra_logistica_integracao_id', '')::BIGINT,
    COALESCE((p_order->>'personalizado')::BOOLEAN, false),
    NULLIF(p_order->>'canal_venda_id', '')::INTEGER,
    COALESCE(p_order->'customer', '{}'::jsonb),
    NULLIF(p_order->>'pedido_bling_id', '')::BIGINT,
    NULLIF(p_order->>'pedido_shopee_id', '')::BIGINT,
    NULLIF(p_order->>'pedido_mercadolivre_id', '')::INTEGER,
    NULLIF(p_order->>'buyer_username', ''),
    NULLIF(p_order->>'shipping_carrier', ''),
    NULLIF(p_order->>'message_to_seller', ''),
    now()
  )
  ON CONFLICT (marketplace_module_id, marketplace_order_id)
  DO UPDATE SET
    marketplace_integration_id = COALESCE(EXCLUDED.marketplace_integration_id, public.pedidos.marketplace_integration_id),
    ingest_source = COALESCE(EXCLUDED.ingest_source, public.pedidos.ingest_source),
    erp_integration_id = COALESCE(EXCLUDED.erp_integration_id, public.pedidos.erp_integration_id),
    erp_store_id = COALESCE(EXCLUDED.erp_store_id, public.pedidos.erp_store_id),
    erp_order_id = COALESCE(EXCLUDED.erp_order_id, public.pedidos.erp_order_id),
    erp_order_number = COALESCE(EXCLUDED.erp_order_number, public.pedidos.erp_order_number),
    situacao_pedido_id = COALESCE(EXCLUDED.situacao_pedido_id, public.pedidos.situacao_pedido_id),
    status_original = COALESCE(EXCLUDED.status_original, public.pedidos.status_original),
    total_pedido = COALESCE(EXCLUDED.total_pedido, public.pedidos.total_pedido),
    moeda = COALESCE(EXCLUDED.moeda, public.pedidos.moeda),
    data_venda = COALESCE(EXCLUDED.data_venda, public.pedidos.data_venda),
    cliente_nome = COALESCE(EXCLUDED.cliente_nome, public.pedidos.cliente_nome),
    cliente_documento = COALESCE(EXCLUDED.cliente_documento, public.pedidos.cliente_documento),
    cliente_telefone = COALESCE(EXCLUDED.cliente_telefone, public.pedidos.cliente_telefone),
    cliente_email = COALESCE(EXCLUDED.cliente_email, public.pedidos.cliente_email),
    is_flex = CASE WHEN p_order ? 'is_flex' THEN EXCLUDED.is_flex ELSE public.pedidos.is_flex END,
    is_fulfillment = CASE WHEN p_order ? 'is_fulfillment' THEN EXCLUDED.is_fulfillment ELSE public.pedidos.is_fulfillment END,
    modalidade_logistica = COALESCE(EXCLUDED.modalidade_logistica, public.pedidos.modalidade_logistica),
    servico_logistico = COALESCE(EXCLUDED.servico_logistico, public.pedidos.servico_logistico),
    data_limite_envio = COALESCE(EXCLUDED.data_limite_envio, public.pedidos.data_limite_envio),
    data_compra_marketplace = COALESCE(EXCLUDED.data_compra_marketplace, public.pedidos.data_compra_marketplace),
    data_pagamento_marketplace = COALESCE(EXCLUDED.data_pagamento_marketplace, public.pedidos.data_pagamento_marketplace),
    data_coleta = COALESCE(EXCLUDED.data_coleta, public.pedidos.data_coleta),
    data_envio_marketplace = COALESCE(EXCLUDED.data_envio_marketplace, public.pedidos.data_envio_marketplace),
    regra_logistica_integracao_id = COALESCE(EXCLUDED.regra_logistica_integracao_id, public.pedidos.regra_logistica_integracao_id),
    personalizado = CASE WHEN p_order ? 'personalizado' THEN EXCLUDED.personalizado ELSE public.pedidos.personalizado END,
    canal_venda_id = COALESCE(EXCLUDED.canal_venda_id, public.pedidos.canal_venda_id),
    informacoes_cliente = CASE
      WHEN EXCLUDED.informacoes_cliente = '{}'::jsonb THEN public.pedidos.informacoes_cliente
      ELSE EXCLUDED.informacoes_cliente
    END,
    pedido_bling_id = COALESCE(EXCLUDED.pedido_bling_id, public.pedidos.pedido_bling_id),
    pedido_shopee_id = COALESCE(EXCLUDED.pedido_shopee_id, public.pedidos.pedido_shopee_id),
    pedido_mercadolivre_id = COALESCE(EXCLUDED.pedido_mercadolivre_id, public.pedidos.pedido_mercadolivre_id),
    buyer_username = COALESCE(EXCLUDED.buyer_username, public.pedidos.buyer_username),
    shipping_carrier = COALESCE(EXCLUDED.shipping_carrier, public.pedidos.shipping_carrier),
    message_to_seller = COALESCE(EXCLUDED.message_to_seller, public.pedidos.message_to_seller),
    updated_at = now()
  RETURNING id INTO v_pedido_id;

  IF p_snapshot IS NOT NULL THEN
    INSERT INTO public.pedido_snapshots (
      pedido_id, identity, customer, items, logistics, financial,
      platform_fields, raw_refs, source_history, updated_at
    ) VALUES (
      v_pedido_id,
      COALESCE(p_snapshot->'identity', '{}'::jsonb),
      COALESCE(p_snapshot->'customer', '{}'::jsonb),
      COALESCE(p_snapshot->'items', '[]'::jsonb),
      COALESCE(p_snapshot->'logistics', '{}'::jsonb),
      COALESCE(p_snapshot->'financial', '{}'::jsonb),
      COALESCE(p_snapshot->'platform_fields', '{}'::jsonb),
      COALESCE(p_snapshot->'raw_refs', '{}'::jsonb),
      COALESCE(p_snapshot->'source_history', '[]'::jsonb),
      now()
    )
    ON CONFLICT (pedido_id) DO UPDATE SET
      identity = public.pedido_snapshots.identity || EXCLUDED.identity,
      customer = public.pedido_snapshots.customer || EXCLUDED.customer,
      items = CASE WHEN EXCLUDED.items = '[]'::jsonb
        THEN public.pedido_snapshots.items ELSE EXCLUDED.items END,
      logistics = public.pedido_snapshots.logistics || EXCLUDED.logistics,
      financial = public.pedido_snapshots.financial || EXCLUDED.financial,
      platform_fields = public.pedido_snapshots.platform_fields || EXCLUDED.platform_fields,
      raw_refs = public.pedido_snapshots.raw_refs || EXCLUDED.raw_refs,
      source_history = COALESCE(public.pedido_snapshots.source_history, '[]'::jsonb)
        || COALESCE(EXCLUDED.source_history, '[]'::jsonb),
      updated_at = now();
  END IF;

  FOR v_ref IN
    SELECT value FROM jsonb_array_elements(COALESCE(p_refs, '[]'::jsonb))
  LOOP
    IF v_ref->>'role' = 'sales_origin' THEN
      INSERT INTO public.pedido_integration_refs (
        pedido_id, integration_id, module_id, role, external_order_id,
        external_record_id, external_status, last_synced_at, metadata
      ) VALUES (
        v_pedido_id,
        NULLIF(v_ref->>'integration_id', '')::INTEGER,
        lower(v_ref->>'module_id'),
        'sales_origin',
        v_ref->>'external_order_id',
        NULLIF(v_ref->>'external_record_id', ''),
        NULLIF(v_ref->>'external_status', ''),
        COALESCE(NULLIF(v_ref->>'last_synced_at', '')::TIMESTAMPTZ, now()),
        COALESCE(v_ref->'metadata', '{}'::jsonb)
      )
      ON CONFLICT (module_id, external_order_id)
        WHERE role = 'sales_origin'
      DO UPDATE SET
        pedido_id = EXCLUDED.pedido_id,
        integration_id = COALESCE(EXCLUDED.integration_id, public.pedido_integration_refs.integration_id),
        external_record_id = COALESCE(EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id),
        external_status = COALESCE(EXCLUDED.external_status, public.pedido_integration_refs.external_status),
        last_synced_at = EXCLUDED.last_synced_at,
        metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
        updated_at = now();
    ELSE
      INSERT INTO public.pedido_integration_refs (
        pedido_id, integration_id, module_id, role, external_order_id,
        external_record_id, external_status, last_synced_at, metadata
      ) VALUES (
        v_pedido_id,
        NULLIF(v_ref->>'integration_id', '')::INTEGER,
        lower(v_ref->>'module_id'),
        v_ref->>'role',
        v_ref->>'external_order_id',
        NULLIF(v_ref->>'external_record_id', ''),
        NULLIF(v_ref->>'external_status', ''),
        COALESCE(NULLIF(v_ref->>'last_synced_at', '')::TIMESTAMPTZ, now()),
        COALESCE(v_ref->'metadata', '{}'::jsonb)
      )
      ON CONFLICT (pedido_id, integration_id, role)
      DO UPDATE SET
        module_id = EXCLUDED.module_id,
        external_order_id = EXCLUDED.external_order_id,
        external_record_id = COALESCE(EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id),
        external_status = COALESCE(EXCLUDED.external_status, public.pedido_integration_refs.external_status),
        last_synced_at = EXCLUDED.last_synced_at,
        metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
        updated_at = now();
    END IF;
  END LOOP;

  UPDATE public.pending_marketplace_enrichments
     SET status = CASE WHEN COALESCE(p_order->>'ingest_source', '') = 'bling'
                       THEN 'applied' ELSE 'matched' END,
         matched_pedido_id = v_pedido_id,
         applied_at = CASE WHEN COALESCE(p_order->>'ingest_source', '') = 'bling'
                           THEN now() ELSE applied_at END,
         updated_at = now()
   WHERE marketplace_module_id = v_module_id
     AND marketplace_order_id = v_marketplace_order_id
     AND status = 'pending';

  UPDATE public.pending_order_reconciliations
     SET pedido_id = v_pedido_id, status = 'applied', resolved_at = now(), updated_at = now()
   WHERE status = 'pending'
     AND erp_integration_id = NULLIF(p_order->>'erp_integration_id', '')::INTEGER
     AND erp_order_id = NULLIF(p_order->>'erp_order_id', '')::BIGINT;

  RETURN v_pedido_id;
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_canonical_order(JSONB, JSONB, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.upsert_canonical_order(JSONB, JSONB, JSONB) TO service_role;
