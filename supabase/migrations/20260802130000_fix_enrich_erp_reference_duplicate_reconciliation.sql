-- Corrige 23505 em reconcile_pending_erp_references:
-- duplicate key (erp_integration_id, erp_order_id, status)=(.., .., applied).
--
-- Causa: um pedido pode ter mais de uma linha 'pending' em
-- pending_order_reconciliations resolvendo para a mesma chave ERP (ou o
-- ultimo UPDATE de enrich_order_erp_reference casa por pedido_id OU por
-- erp_integration_id+erp_store_id+erp_order_id — de proposito, para fechar
-- pending orfaos da mesma referencia). Quando mais de uma linha 'pending'
-- casa nessas condicoes, o UPDATE tenta gravar 'applied' duas vezes para a
-- mesma chave e esbarra em ux_pending_order_reconciliation_erp_order.
--
-- Correcao: so aplica 'applied' em quem ainda nao tem gemeo aplicado na
-- mesma chave (erp_integration_id, erp_order_id); o resto vira
-- 'skipped_duplicate' em vez de derrubar a task.
ALTER TABLE public.pending_order_reconciliations
  DROP CONSTRAINT IF EXISTS pending_order_reconciliations_status_check;

ALTER TABLE public.pending_order_reconciliations
  ADD CONSTRAINT pending_order_reconciliations_status_check
  CHECK (status = ANY (ARRAY[
    'pending'::text, 'matched'::text, 'applied'::text, 'expired'::text,
    'failed'::text, 'skipped_terminal'::text, 'skipped_duplicate'::text
  ]));

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
  v_pedido_bling_id INTEGER;
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

  -- NB: `pedidos` nao tem colunas bling_integration_id/bling_loja_id/
  -- bling_order_id/bling_order_number (essas existem em `pedidos_bling`, a
  -- tabela espelho do ERP, ja gravada acima). Escrever nelas aqui derruba a
  -- task com 42703 — foi o que aconteceu quando esta migration recriou a
  -- funcao copiando o texto do arquivo 20260731110000 sem notar que o schema
  -- de producao ja tinha se afastado dele.
  UPDATE public.pedidos
     SET erp_integration_id = p_erp_integration_id,
         erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id,
         erp_order_number = p_erp_order_number,
         numero_pedido = p_erp_order_number,
         pedido_bling_id = v_pedido_bling_id,
         updated_at = now()
   WHERE id = v_pedido_id;

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

  -- So marca 'applied' quem ainda nao tem gemeo aplicado na mesma chave
  -- (erp_integration_id, erp_order_id). Evita o 23505 quando mais de uma
  -- linha 'pending' casa (por pedido_id ou pela propria chave ERP).
  UPDATE public.pending_order_reconciliations t
     SET status = 'applied', resolved_at = now(), updated_at = now(), last_error = NULL,
         erp_integration_id = p_erp_integration_id, erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id
   WHERE t.status = 'pending'
     AND (
       t.pedido_id = v_pedido_id
       OR (
         t.erp_integration_id = p_erp_integration_id
         AND t.erp_store_id = p_erp_store_id
         AND t.erp_order_id = p_erp_order_id
       )
     )
     AND NOT EXISTS (
       SELECT 1 FROM public.pending_order_reconciliations a
        WHERE a.erp_integration_id = p_erp_integration_id
          AND a.erp_order_id = p_erp_order_id
          AND a.status = 'applied'
     );

  -- As demais linhas 'pending' que casariam sao duplicatas de uma referencia
  -- ja aplicada: encerra sem tentar reaplicar a mesma chave.
  UPDATE public.pending_order_reconciliations t
     SET status = 'skipped_duplicate', resolved_at = now(), updated_at = now(),
         last_error = 'Referencia ERP ja aplicada por outro registro de reconciliacao'
   WHERE t.status = 'pending'
     AND (
       t.pedido_id = v_pedido_id
       OR (
         t.erp_integration_id = p_erp_integration_id
         AND t.erp_store_id = p_erp_store_id
         AND t.erp_order_id = p_erp_order_id
       )
     );

  RETURN v_pedido_id;
END;
$$;

REVOKE ALL ON FUNCTION public.enrich_order_erp_reference(BIGINT, INTEGER, TEXT, BIGINT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enrich_order_erp_reference(BIGINT, INTEGER, TEXT, BIGINT, TEXT, TEXT) TO service_role;

-- Destrava linhas ja presas no estado atual (ex.: pedido 54453): pending sem
-- gemeo aplicado nao mexe; pending com gemeo ja aplicado (mesma
-- erp_integration_id/erp_order_id, ou mesmo pedido_id ja resolvido) vira
-- skipped_duplicate.
UPDATE public.pending_order_reconciliations t
   SET status = 'skipped_duplicate', resolved_at = now(), updated_at = now(),
       last_error = 'Referencia ERP ja aplicada por outro registro de reconciliacao'
 WHERE t.status = 'pending'
   AND (
     EXISTS (
       SELECT 1 FROM public.pending_order_reconciliations a
        WHERE a.pedido_id = t.pedido_id
          AND a.status = 'applied'
     )
     OR (
       t.erp_integration_id IS NOT NULL AND t.erp_order_id IS NOT NULL
       AND EXISTS (
         SELECT 1 FROM public.pending_order_reconciliations a
          WHERE a.erp_integration_id = t.erp_integration_id
            AND a.erp_order_id = t.erp_order_id
            AND a.status = 'applied'
       )
     )
   );
