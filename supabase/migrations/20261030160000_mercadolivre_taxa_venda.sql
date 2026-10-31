-- Reuse already-collected evidence; do not request the provider again or infer net payout.
CREATE FUNCTION public.gestao_ml_taxa_venda_backfill(p_after integer DEFAULT 0,p_limit integer DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE item record; processed integer:=0; updated integer:=0; next_id integer:=p_after; fee jsonb;
BEGIN
 IF p_after<0 OR p_limit<1 OR p_limit>250 THEN RAISE EXCEPTION 'INVALID_BATCH' USING ERRCODE='22023'; END IF;
 FOR item IN SELECT g.pedido_id,g.evidence,p.codigo_pedido_externo,g.components
  FROM public.gestao_financeiro g JOIN public.pedidos p ON p.id=g.pedido_id
  WHERE g.source='ml_billing' AND g.pedido_id>p_after ORDER BY g.pedido_id LIMIT p_limit FOR UPDATE OF g
 LOOP
  processed:=processed+1;next_id:=item.pedido_id;
  IF jsonb_array_length(CASE WHEN jsonb_typeof(item.evidence->'results')='array' THEN item.evidence->'results' ELSE '[]'::jsonb END)=1
   AND jsonb_array_length(CASE WHEN jsonb_typeof(item.evidence->'errors')='array' THEN item.evidence->'errors' ELSE '[null]'::jsonb END)=0
   AND item.evidence->>'total'='1' AND item.evidence->'results'->0->>'order_id'=item.codigo_pedido_externo
   AND (CASE WHEN jsonb_typeof(item.evidence->'results'->0->'sale_fee'->'net')='number'
       THEN (item.evidence->'results'->0->'sale_fee'->>'net')::numeric>=0 ELSE false END) THEN
   fee:=item.evidence->'results'->0->'sale_fee'->'net';
   IF item.components->'sale_fee' IS DISTINCT FROM fee THEN
    UPDATE public.gestao_financeiro SET components=coalesce(components,'{}'::jsonb)||jsonb_build_object('sale_fee',fee),updated_at=now()
     WHERE pedido_id=item.pedido_id AND source='ml_billing';
    updated:=updated+1;
   END IF;
  END IF;
 END LOOP;
 RETURN jsonb_build_object('processed',processed,'updated',updated,'next_after',next_id,'has_more',processed=p_limit);
END $$;
REVOKE ALL ON FUNCTION public.gestao_ml_taxa_venda_backfill(integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.gestao_ml_taxa_venda_backfill(integer,integer) TO service_role;
