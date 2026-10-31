CREATE OR REPLACE FUNCTION public.gestao_ml_taxa_venda_backfill(p_after integer DEFAULT 0,p_limit integer DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE item record; processed integer:=0; updated integer:=0; next_id integer:=p_after; fee jsonb; matches jsonb;
BEGIN
 IF p_after<0 OR p_limit<1 OR p_limit>250 THEN RAISE EXCEPTION 'INVALID_BATCH' USING ERRCODE='22023'; END IF;
 FOR item IN SELECT g.pedido_id,g.evidence,p.codigo_pedido_externo,g.components
  FROM public.gestao_financeiro g JOIN public.pedidos p ON p.id=g.pedido_id
  WHERE g.source='ml_billing' AND g.pedido_id>p_after ORDER BY g.pedido_id LIMIT p_limit FOR UPDATE OF g
 LOOP
  processed:=processed+1;next_id:=item.pedido_id;
  IF jsonb_typeof(item.evidence->'results') IS DISTINCT FROM 'array'
   OR jsonb_typeof(item.evidence->'errors') IS DISTINCT FROM 'array' THEN CONTINUE; END IF;
  IF jsonb_array_length(item.evidence->'errors')<>0 OR coalesce(item.evidence->>'total','') !~ '^[0-9]+$' THEN CONTINUE; END IF;
  IF (item.evidence->>'total')::numeric<>jsonb_array_length(item.evidence->'results') THEN CONTINUE; END IF;
  SELECT coalesce(jsonb_agg(value),'[]') INTO matches FROM jsonb_array_elements(item.evidence->'results')
   WHERE value->>'order_id'=item.codigo_pedido_externo;
  IF jsonb_array_length(matches)<>1 THEN CONTINUE; END IF;
  fee:=matches->0->'sale_fee'->'net';
  IF jsonb_typeof(fee) IS DISTINCT FROM 'number' THEN CONTINUE; END IF;
  IF (fee #>> '{}')::numeric<0 THEN CONTINUE; END IF;
  IF item.components->'sale_fee' IS DISTINCT FROM fee THEN
   UPDATE public.gestao_financeiro SET components=coalesce(components,'{}'::jsonb)||jsonb_build_object('sale_fee',fee),updated_at=now()
    WHERE pedido_id=item.pedido_id AND source='ml_billing';
   updated:=updated+1;
  END IF;
 END LOOP;
 RETURN jsonb_build_object('processed',processed,'updated',updated,'next_after',next_id,'has_more',processed=p_limit);
END $$;
