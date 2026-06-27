-- Marketplace-first canonical orders. ERP is enrichment, not an ingest prerequisite.

DROP FUNCTION IF EXISTS public.effective_purchase_date(timestamptz, timestamp, timestamp);
CREATE OR REPLACE FUNCTION public.effective_purchase_date(
    p_data_compra_marketplace timestamptz,
    p_data_venda timestamp,
    p_created_at timestamp
)
RETURNS timestamptz
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT COALESCE(p_data_compra_marketplace, p_data_venda, p_created_at);
$$;

CREATE OR REPLACE FUNCTION public.enforce_marketplace_order_authority()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF lower(COALESCE(OLD.ingest_source, '')) IN ('shopee', 'mercadolivre')
     AND lower(COALESCE(NEW.ingest_source, '')) = 'bling' THEN
    NEW.ingest_source := OLD.ingest_source;
    NEW.marketplace_integration_id := COALESCE(OLD.marketplace_integration_id, NEW.marketplace_integration_id);
    NEW.situacao_pedido_id := OLD.situacao_pedido_id;
    NEW.status_original := OLD.status_original;
    NEW.total_pedido := OLD.total_pedido;
    NEW.moeda := OLD.moeda;
    NEW.data_venda := OLD.data_venda;
    NEW.cliente_nome := OLD.cliente_nome;
    NEW.cliente_documento := OLD.cliente_documento;
    NEW.cliente_telefone := OLD.cliente_telefone;
    NEW.cliente_email := OLD.cliente_email;
    NEW.informacoes_cliente := OLD.informacoes_cliente;
    NEW.is_flex := OLD.is_flex;
    NEW.is_fulfillment := OLD.is_fulfillment;
    NEW.modalidade_logistica := OLD.modalidade_logistica;
    NEW.servico_logistico := OLD.servico_logistico;
    NEW.data_limite_envio := OLD.data_limite_envio;
    NEW.data_compra_marketplace := OLD.data_compra_marketplace;
    NEW.data_pagamento_marketplace := OLD.data_pagamento_marketplace;
    NEW.data_coleta := OLD.data_coleta;
    NEW.data_envio_marketplace := OLD.data_envio_marketplace;
    NEW.regra_logistica_integracao_id := OLD.regra_logistica_integracao_id;
    NEW.personalizado := OLD.personalizado;
    NEW.canal_venda_id := COALESCE(OLD.canal_venda_id, NEW.canal_venda_id);
    NEW.buyer_username := OLD.buyer_username;
    NEW.shipping_carrier := OLD.shipping_carrier;
    NEW.message_to_seller := OLD.message_to_seller;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_marketplace_order_authority ON public.pedidos;
CREATE TRIGGER trg_enforce_marketplace_order_authority
BEFORE UPDATE ON public.pedidos
FOR EACH ROW EXECUTE FUNCTION public.enforce_marketplace_order_authority();

CREATE OR REPLACE FUNCTION public.sync_marketplace_snapshot_items()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_source text := lower(COALESCE(NEW.identity->>'ingest_source', ''));
BEGIN
  IF v_source NOT IN ('shopee', 'mercadolivre')
     OR jsonb_typeof(NEW.items) <> 'array'
     OR jsonb_array_length(NEW.items) = 0 THEN
    RETURN NEW;
  END IF;

  DELETE FROM public.itens_pedido WHERE pedido_id = NEW.pedido_id;
  INSERT INTO public.itens_pedido (
    pedido_id, produto_id, sku_externo, descricao, quantidade,
    preco_unitario, subtotal, created_at, updated_at
  )
  SELECT
    NEW.pedido_id,
    COALESCE(
      NULLIF(item->>'produto_id', '')::integer,
      (SELECT vb.produto_id FROM public.vinculos_bling vb
       WHERE vb.codigo_bling = COALESCE(item->>'sku', item->>'sku_externo') LIMIT 1),
      (SELECT p.id FROM public.produtos p
       WHERE p.sku = COALESCE(item->>'sku', item->>'sku_externo') LIMIT 1)
    ),
    COALESCE(item->>'sku', item->>'sku_externo'),
    COALESCE(item->>'name', item->>'descricao'),
    COALESCE(NULLIF(item->>'quantity', '')::numeric, NULLIF(item->>'quantidade', '')::numeric, 1),
    COALESCE(NULLIF(item->>'unit_price', '')::numeric, NULLIF(item->>'preco_unitario', '')::numeric, NULLIF(item->>'price', '')::numeric, 0),
    COALESCE(
      NULLIF(item->>'subtotal', '')::numeric,
      COALESCE(NULLIF(item->>'quantity', '')::numeric, NULLIF(item->>'quantidade', '')::numeric, 1)
      * COALESCE(NULLIF(item->>'unit_price', '')::numeric, NULLIF(item->>'preco_unitario', '')::numeric, NULLIF(item->>'price', '')::numeric, 0)
    ),
    now(), now()
  FROM jsonb_array_elements(NEW.items) AS item;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sync_marketplace_snapshot_items ON public.pedido_snapshots;
CREATE TRIGGER trg_sync_marketplace_snapshot_items
AFTER INSERT OR UPDATE OF items, identity ON public.pedido_snapshots
FOR EACH ROW EXECUTE FUNCTION public.sync_marketplace_snapshot_items();

DROP INDEX IF EXISTS public.idx_pedidos_purchase_order;
CREATE INDEX IF NOT EXISTS idx_pedidos_purchase_order
ON public.pedidos (
    public.effective_purchase_date(data_compra_marketplace, data_venda, created_at) DESC,
    id DESC
);

CREATE OR REPLACE FUNCTION public.list_pedidos_por_compra(
    p_situacao_pedido_id INTEGER DEFAULT NULL,
    p_canal_venda_id INTEGER DEFAULT NULL,
    p_origem_pedido_key TEXT DEFAULT NULL,
    p_bling_integration_id INTEGER DEFAULT NULL,
    p_has_demanda BOOLEAN DEFAULT NULL,
    p_is_flex BOOLEAN DEFAULT NULL,
    p_is_personalizado BOOLEAN DEFAULT NULL,
    p_is_fulfillment BOOLEAN DEFAULT NULL,
    p_delivery_start_date TEXT DEFAULT NULL,
    p_delivery_end_date TEXT DEFAULT NULL,
    p_pedido_date_start TEXT DEFAULT NULL,
    p_pedido_date_end TEXT DEFAULT NULL,
    p_search_term TEXT DEFAULT NULL,
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (order_data JSONB)
LANGUAGE sql
STABLE
AS $$
  SELECT to_jsonb(row_data)
  FROM public.list_pedidos_filtrados(
    p_situacao_pedido_id, p_canal_venda_id, p_origem_pedido_key,
    p_bling_integration_id, p_has_demanda, p_is_flex, p_is_personalizado,
    p_is_fulfillment, p_delivery_start_date, p_delivery_end_date,
    p_pedido_date_start, p_pedido_date_end, p_search_term,
    'created_at', 'desc', 2147483647, 0
  ) AS row_data
  ORDER BY COALESCE(
    row_data.data_compra_marketplace,
    row_data.data_venda,
    row_data.created_at
  ) DESC NULLS LAST, row_data.id DESC
  LIMIT p_limit OFFSET p_offset;
$$;

REVOKE ALL ON FUNCTION public.list_pedidos_por_compra FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.list_pedidos_por_compra TO authenticated;
GRANT EXECUTE ON FUNCTION public.list_pedidos_por_compra TO service_role;

UPDATE public.configuracoes_aplicacao
SET valor = jsonb_set(
  CASE WHEN jsonb_typeof(valor) = 'string' THEN (valor #>> '{}')::jsonb ELSE valor END,
  '{task_schedules,reconcile-pending-erp-references}',
  '{"enabled":true,"schedule_seconds":60,"description":"Resolve referências ERP de pedidos canônicos","task_name":"nistiprint_shared.services.order_erp_reference_service.reconcile_pending"}'::jsonb,
  true
)
WHERE nome = 'celery_task_schedules';
