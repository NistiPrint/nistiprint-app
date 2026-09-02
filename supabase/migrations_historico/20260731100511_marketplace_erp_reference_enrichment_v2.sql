-- Persist ERP/Bling identity after direct marketplace ingest.
CREATE OR REPLACE FUNCTION public.enrich_order_erp_reference(
  p_pedido_id BIGINT,
  p_erp_integration_id INTEGER,
  p_erp_store_id TEXT,
  p_erp_order_id BIGINT,
  p_erp_order_number TEXT,
  p_marketplace_order_id TEXT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
  v_pedido_id BIGINT;
BEGIN
  SELECT id INTO v_pedido_id
  FROM public.pedidos
  WHERE id = p_pedido_id
     OR (p_marketplace_order_id IS NOT NULL
         AND marketplace_order_id = p_marketplace_order_id)
  ORDER BY CASE WHEN id = p_pedido_id THEN 0 ELSE 1 END, id
  LIMIT 1
  FOR UPDATE;

  IF v_pedido_id IS NULL THEN
    RAISE EXCEPTION 'Pedido canonico nao encontrado para enriquecimento';
  END IF;

  UPDATE public.pedidos
     SET erp_integration_id = p_erp_integration_id,
         erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id,
         erp_order_number = p_erp_order_number,
         bling_integration_id = p_erp_integration_id,
         bling_loja_id = p_erp_store_id,
         bling_order_id = p_erp_order_id,
         bling_order_number = p_erp_order_number,
         numero_pedido = p_erp_order_number,
         updated_at = now()
   WHERE id = v_pedido_id;

  UPDATE public.pedido_snapshots
     SET identity = identity || jsonb_build_object(
           'erp_integration_id', p_erp_integration_id,
           'erp_store_id', p_erp_store_id,
           'erp_order_id', p_erp_order_id,
           'erp_order_number', p_erp_order_number,
           'bling_integration_id', p_erp_integration_id,
           'bling_loja_id', p_erp_store_id,
           'bling_order_id', p_erp_order_id,
           'bling_order_number', p_erp_order_number
         ),
         raw_refs = raw_refs || jsonb_build_object(
           'bling_lookup', jsonb_build_object(
             'status', 'found',
             'bling_integration_id', p_erp_integration_id,
             'bling_order_id', p_erp_order_id,
             'bling_order_number', p_erp_order_number,
             'numero_loja', p_marketplace_order_id
           )
         ),
         updated_at = now()
   WHERE pedido_id = v_pedido_id;

  INSERT INTO public.pedido_integration_refs (
    pedido_id, integration_id, module_id, role, external_order_id,
    external_record_id, metadata, last_synced_at
  )
  SELECT v_pedido_id, p_erp_integration_id, 'bling', 'erp',
         p_marketplace_order_id, p_erp_order_id::TEXT,
         jsonb_build_object('store_id', p_erp_store_id, 'order_number', p_erp_order_number),
         now()
  WHERE p_erp_integration_id IS NOT NULL
  ON CONFLICT (pedido_id, integration_id, role)
  DO UPDATE SET
    external_order_id = EXCLUDED.external_order_id,
    external_record_id = EXCLUDED.external_record_id,
    metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
    last_synced_at = now(),
    updated_at = now();

  UPDATE public.pending_order_reconciliations
     SET status = 'applied', resolved_at = now(), updated_at = now(), last_error = NULL,
         erp_integration_id = p_erp_integration_id, erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id
   WHERE pedido_id = v_pedido_id AND status = 'pending';

  RETURN v_pedido_id;
END;
$$;

REVOKE ALL ON FUNCTION public.enrich_order_erp_reference(BIGINT, INTEGER, TEXT, BIGINT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enrich_order_erp_reference(BIGINT, INTEGER, TEXT, BIGINT, TEXT, TEXT) TO service_role;

UPDATE public.integration_status_mappings
SET internal_situacao_pedido_id = 2,
    triggers_demand_consolidation = true
WHERE module_id = 'mercadolivre'
  AND status_domain = 'shipping'
  AND external_status_id IN ('to_be_shipped', 'handling', 'ready_to_ship');