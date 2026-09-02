-- `enrich_order_erp_reference` aplica a referencia no pacote inteiro.
--
-- Antes, cada irmao do pacote descobria sozinho o mesmo pedido do Bling e
-- tentava reivindica-lo, um por rodada da fila. Com o indice unico removido
-- (ver 20260803092000), isso deixaria de dar erro — mas continuaria gastando
-- uma consulta ao Bling por irmao para chegar ao mesmo resultado.
--
-- Resolver o pacote de uma vez fecha os dois problemas: o irmao ja nasce
-- enriquecido e a fila dele e encerrada na mesma transacao. A alternativa,
-- deixar cada irmao se resolver, e uma corrida com N-1 perdedores.
--
-- `AND erp_order_id IS NULL` no UPDATE: um irmao que ja tenha referencia de
-- outro pedido do ERP nao e sobrescrito. Propagar e preencher vazio, nunca
-- reescrever decisao anterior.

CREATE OR REPLACE FUNCTION public.enrich_order_erp_reference(
  p_pedido_id bigint,
  p_erp_integration_id integer,
  p_erp_store_id text,
  p_erp_order_id bigint,
  p_erp_order_number text,
  p_marketplace_order_id text DEFAULT NULL::text
)
RETURNS bigint
LANGUAGE plpgsql
SET search_path TO 'public'
AS $function$
DECLARE
  v_pedido_id BIGINT;
  v_pedido_bling_id INTEGER;
  v_pack_id TEXT;
BEGIN
  SELECT id, pack_id INTO v_pedido_id, v_pack_id
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

  INSERT INTO public.pedidos_bling (
    numero_pedido, loja_id, bling_id, numero_loja, raw_payload,
    bling_integration_id, updated_at
  ) VALUES (
    p_erp_order_number,
    CASE WHEN COALESCE(p_erp_store_id, '') ~ '^[0-9]+$'
         THEN p_erp_store_id::INTEGER ELSE NULL END,
    p_erp_order_id,
    p_marketplace_order_id,
    jsonb_build_object(
      'reference_only', true,
      'id', p_erp_order_id,
      'numero', p_erp_order_number,
      'numeroLoja', p_marketplace_order_id,
      'loja_id', p_erp_store_id
    ),
    p_erp_integration_id,
    now()
  )
  ON CONFLICT (bling_integration_id, bling_id)
  DO UPDATE SET
    numero_pedido = EXCLUDED.numero_pedido,
    loja_id = COALESCE(EXCLUDED.loja_id, public.pedidos_bling.loja_id),
    numero_loja = COALESCE(EXCLUDED.numero_loja, public.pedidos_bling.numero_loja),
    raw_payload = public.pedidos_bling.raw_payload || EXCLUDED.raw_payload,
    updated_at = now()
  RETURNING id INTO v_pedido_bling_id;

  UPDATE public.pedidos
     SET erp_integration_id = p_erp_integration_id,
         erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id,
         erp_order_number = p_erp_order_number,
         numero_pedido = p_erp_order_number,
         pedido_bling_id = v_pedido_bling_id,
         updated_at = now()
   WHERE id = v_pedido_id
      OR (v_pack_id IS NOT NULL AND pack_id = v_pack_id AND erp_order_id IS NULL);

  UPDATE public.pedido_snapshots
     SET identity = identity || jsonb_build_object(
           'erp_integration_id', p_erp_integration_id,
           'erp_store_id', p_erp_store_id,
           'erp_order_id', p_erp_order_id,
           'erp_order_number', p_erp_order_number
         ),
         raw_refs = raw_refs || jsonb_build_object(
           'bling_lookup', jsonb_build_object(
             'status', 'found',
             'erp_integration_id', p_erp_integration_id,
             'erp_order_id', p_erp_order_id,
             'erp_order_number', p_erp_order_number,
             'numero_loja', p_marketplace_order_id
           )
         ),
         updated_at = now()
   WHERE pedido_id IN (
       SELECT id FROM public.pedidos
        WHERE id = v_pedido_id
           OR (v_pack_id IS NOT NULL AND pack_id = v_pack_id)
   );

  INSERT INTO public.pedido_integration_refs (
    pedido_id, integration_id, module_id, role, external_order_id,
    external_record_id, metadata, last_synced_at
  )
  SELECT pd.id, p_erp_integration_id, 'bling', 'erp',
         pd.marketplace_order_id, p_erp_order_id::TEXT,
         jsonb_build_object('store_id', p_erp_store_id, 'order_number', p_erp_order_number),
         now()
    FROM public.pedidos pd
   WHERE p_erp_integration_id IS NOT NULL
     AND (pd.id = v_pedido_id
          OR (v_pack_id IS NOT NULL AND pd.pack_id = v_pack_id))
  ON CONFLICT (pedido_id, integration_id, role)
  DO UPDATE SET
    external_order_id = EXCLUDED.external_order_id,
    external_record_id = EXCLUDED.external_record_id,
    metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
    last_synced_at = now(),
    updated_at = now();

  -- Encerra a fila do pedido e a dos irmaos do pacote.
  UPDATE public.pending_order_reconciliations t
     SET status = 'applied', resolved_at = now(), updated_at = now(), last_error = NULL,
         erp_integration_id = p_erp_integration_id, erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id
   WHERE t.status = 'pending'
     AND (
       t.pedido_id IN (
         SELECT id FROM public.pedidos
          WHERE id = v_pedido_id
             OR (v_pack_id IS NOT NULL AND pack_id = v_pack_id)
       )
       OR (
         t.erp_integration_id = p_erp_integration_id
         AND t.erp_store_id = p_erp_store_id
         AND t.erp_order_id = p_erp_order_id
       )
     );

  RETURN v_pedido_id;
END;
$function$;

COMMENT ON FUNCTION public.enrich_order_erp_reference(bigint, integer, text, bigint, text, text) IS
  'Aplica a referencia de ERP no pedido e nos irmaos do mesmo pacote. Um pacote e uma caixa: um pedido no ERP, N pedidos canonicos.';
