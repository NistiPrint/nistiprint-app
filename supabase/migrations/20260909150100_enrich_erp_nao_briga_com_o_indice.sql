-- Restaura a guarda anti-duplicata perdida em 20260803092100.
--
-- 20260802130000 ensinou `enrich_order_erp_reference` a nao gravar 'applied'
-- duas vezes na mesma chave ERP. No dia seguinte, 20260803092100 reescreveu a
-- funcao inteira com CREATE OR REPLACE para adicionar a propagacao por pacote —
-- e levou a guarda junto. O 23505 voltou no mesmo dia; so nao apareceu antes
-- porque a propagacao por pacote (que evitaria a colisao) tambem estava morta
-- por falta de `pack_id` (ver 20260909150000).
--
-- ## Por que 'skipped_duplicate' sai com erp_order_id NULL
--
-- `ux_pending_order_reconciliation_erp_order` e unico em
-- (erp_integration_id, erp_order_id, status) WHERE erp_order_id IS NOT NULL.
-- Num pacote de tres irmaos, marcar dois como 'skipped_duplicate' com o mesmo
-- erp_order_id colidiria igual — o indice nao distingue o status perdedor. O
-- indice nao pode simplesmente cair: `defer_unresolved_erp_order` faz upsert
-- com ON CONFLICT nessas colunas para pedidos sem pedido_id, e precisa dele.
--
-- Entao o vencedor fica com a chave e os demais saem do indice, guardando a
-- referencia em `erp_order_number`. A referencia de verdade mora em `pedidos`;
-- a fila so precisa registrar que o item foi resolvido e por que nao e o dono
-- da chave.

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

  -- Um pacote e uma caixa: os pedidos irmaos vao no mesmo envio e sao faturados
  -- sob o mesmo pedido do ERP. Aplicar a referencia no pacote inteiro de uma vez
  -- resolve os irmaos na primeira passada, em vez de deixa-los tentando
  -- reivindicar o mesmo registro em rodadas seguintes.
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

  -- Encerra a fila do pedido e a dos irmaos do pacote. Um so pode ficar com a
  -- chave (erp_integration_id, erp_order_id, 'applied'); os demais saem
  -- resolvidos como 'skipped_duplicate', fora do indice.
  UPDATE public.pending_order_reconciliations t
     SET status = CASE WHEN a.vencedor THEN 'applied' ELSE 'skipped_duplicate' END,
         resolved_at = now(),
         updated_at = now(),
         last_error = CASE WHEN a.vencedor THEN NULL
                           ELSE 'Irmao de pacote; referencia ERP aplicada no pedido' END,
         erp_integration_id = p_erp_integration_id,
         erp_store_id = p_erp_store_id,
         erp_order_number = COALESCE(p_erp_order_number, t.erp_order_number),
         erp_order_id = CASE WHEN a.vencedor THEN p_erp_order_id ELSE NULL END
    FROM (
      SELECT t2.id,
             (row_number() OVER (ORDER BY t2.pedido_id NULLS LAST, t2.id) = 1
              AND NOT EXISTS (
                SELECT 1
                  FROM public.pending_order_reconciliations x
                 WHERE x.status = 'applied'
                   AND x.erp_integration_id = p_erp_integration_id
                   AND x.erp_order_id = p_erp_order_id
              )) AS vencedor
        FROM public.pending_order_reconciliations t2
       WHERE t2.status = 'pending'
         AND (
           t2.pedido_id IN (
             SELECT id FROM public.pedidos
              WHERE id = v_pedido_id
                 OR (v_pack_id IS NOT NULL AND pack_id = v_pack_id)
           )
           OR (
             t2.erp_integration_id = p_erp_integration_id
             AND t2.erp_store_id = p_erp_store_id
             AND t2.erp_order_id = p_erp_order_id
           )
         )
    ) a
   WHERE t.id = a.id;

  RETURN v_pedido_id;
END;
$function$;
