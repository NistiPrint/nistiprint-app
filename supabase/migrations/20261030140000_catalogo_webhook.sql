-- A targeted refresh never changes the checkpoint or completes a full scan.
CREATE OR REPLACE FUNCTION public.marketplace_catalog_store_item(p_account integer,p_row jsonb,p_observed_at timestamptz)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE external_id text:=p_row->>'item_externo_id'; existing public.marketplace_anuncios%ROWTYPE;
 header_id bigint; unit jsonb; unit_id bigint; active_run uuid;
BEGIN
 IF nullif(external_id,'') IS NULL OR p_observed_at IS NULL OR jsonb_typeof(p_row->'unidades') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'INVALID_CATALOG_OBSERVATION' USING ERRCODE='22023';
 END IF;
 INSERT INTO public.marketplace_catalog_sync(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 SELECT CASE WHEN status='running' THEN run_id ELSE NULL END INTO active_run
  FROM public.marketplace_catalog_sync WHERE account_id=p_account FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtext('catalog_item:'||p_account::text||':'||external_id));
 SELECT * INTO existing FROM public.marketplace_anuncios WHERE integration_id=p_account AND item_externo_id=external_id FOR UPDATE;
 IF FOUND AND (existing.collected_at>p_observed_at OR
  (existing.provider_updated_at IS NOT NULL AND nullif(p_row->>'provider_updated_at','') IS NOT NULL
   AND existing.provider_updated_at>(p_row->>'provider_updated_at')::timestamptz)) THEN RETURN 'stale'; END IF;
 INSERT INTO public.marketplace_anuncios(integration_id,item_externo_id,titulo,imagem_comercial,url,situacao_original,
  situacao_normalizada,user_product_id,familia_externa_id,catalogo_externo_id,provider_updated_at,collected_at,dados_observados,last_seen_run_id)
 VALUES(p_account,external_id,p_row->>'titulo',p_row->>'imagem_comercial',p_row->>'url',p_row->>'situacao_original',
  p_row->>'situacao_normalizada',p_row->>'user_product_id',p_row->>'familia_externa_id',p_row->>'catalogo_externo_id',
  nullif(p_row->>'provider_updated_at','')::timestamptz,clock_timestamp(),coalesce(p_row->'dados_observados','{}'::jsonb),active_run)
 ON CONFLICT(integration_id,item_externo_id) DO UPDATE SET titulo=excluded.titulo,imagem_comercial=excluded.imagem_comercial,
  url=excluded.url,situacao_original=excluded.situacao_original,situacao_normalizada=excluded.situacao_normalizada,
  user_product_id=excluded.user_product_id,familia_externa_id=excluded.familia_externa_id,catalogo_externo_id=excluded.catalogo_externo_id,
  provider_updated_at=excluded.provider_updated_at,collected_at=excluded.collected_at,absent_since=NULL,
  dados_observados=marketplace_anuncios.dados_observados||excluded.dados_observados,
  last_seen_run_id=coalesce(excluded.last_seen_run_id,marketplace_anuncios.last_seen_run_id)
 RETURNING id INTO header_id;
 FOR unit IN SELECT value FROM jsonb_array_elements(p_row->'unidades') LOOP
  SELECT id INTO unit_id FROM public.produto_anuncios WHERE integration_id=p_account AND item_externo_id=external_id
   AND coalesce(variacao_externa_id,'')=coalesce(unit->>'variacao_externa_id','') ORDER BY id LIMIT 1 FOR UPDATE;
  IF unit_id IS NULL THEN
   INSERT INTO public.produto_anuncios(integration_id,item_externo_id,variacao_externa_id,anuncio_id,sku_externo,
    preco_observado,disponibilidade_observada,atributos_variacao,dados_observados)
   VALUES(p_account,external_id,nullif(unit->>'variacao_externa_id',''),header_id,unit->>'sku_externo',
    nullif(unit->>'preco_observado','')::numeric,unit->>'disponibilidade_observada',
    coalesce(unit->'atributos_variacao','{}'::jsonb),coalesce(unit->'dados_observados','{}'::jsonb));
  ELSE
   UPDATE public.produto_anuncios SET anuncio_id=header_id,sku_externo=unit->>'sku_externo',
    preco_observado=nullif(unit->>'preco_observado','')::numeric,disponibilidade_observada=unit->>'disponibilidade_observada',
    atributos_variacao=coalesce(unit->'atributos_variacao','{}'::jsonb),
    dados_observados=dados_observados||coalesce(unit->'dados_observados','{}'::jsonb) WHERE id=unit_id;
  END IF;
  unit_id:=NULL;
 END LOOP;
 RETURN 'updated';
END $$;
REVOKE ALL ON FUNCTION public.marketplace_catalog_store_item(integer,jsonb,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_catalog_store_item(integer,jsonb,timestamptz) TO service_role;

-- A page fetched before a newer targeted observation must not overwrite it.
CREATE OR REPLACE FUNCTION public.marketplace_catalog_sync_store_page(p_account integer,p_owner_token uuid,p_rows jsonb,p_checkpoint jsonb,p_complete boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE listing jsonb; unit jsonb; accepted jsonb:='[]'::jsonb; state public.marketplace_catalog_sync%ROWTYPE;
 old public.marketplace_anuncios%ROWTYPE; observed timestamptz;
BEGIN
 SELECT * INTO state FROM public.marketplace_catalog_sync WHERE account_id=p_account AND owner_token=p_owner_token AND lease_until>now() FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 FOR listing IN SELECT value FROM jsonb_array_elements(coalesce(p_rows,'[]'::jsonb)) ORDER BY value->>'item_externo_id' LOOP
  PERFORM pg_advisory_xact_lock(hashtext('catalog_item:'||p_account::text||':'||(listing->>'item_externo_id')));
  SELECT * INTO old FROM public.marketplace_anuncios WHERE integration_id=p_account AND item_externo_id=listing->>'item_externo_id' FOR UPDATE;
  observed:=coalesce(nullif(listing->>'observed_at','')::timestamptz,clock_timestamp());
  IF FOUND AND (old.collected_at>observed OR (old.provider_updated_at IS NOT NULL AND nullif(listing->>'provider_updated_at','') IS NOT NULL AND old.provider_updated_at>(listing->>'provider_updated_at')::timestamptz)) THEN
   UPDATE public.marketplace_anuncios SET last_seen_run_id=state.run_id,absent_since=NULL WHERE id=old.id;
  ELSE accepted:=accepted||jsonb_build_array(listing); END IF;
 END LOOP;
 IF NOT public.marketplace_catalog_sync_store_page_observed_base(p_account,p_owner_token,accepted,p_checkpoint,p_complete) THEN RETURN false; END IF;
 FOR listing IN SELECT value FROM jsonb_array_elements(accepted) LOOP
  IF jsonb_typeof(listing->'dados_observados')='object' THEN
   UPDATE public.marketplace_anuncios SET dados_observados=dados_observados||(listing->'dados_observados')
    WHERE integration_id=p_account AND item_externo_id=listing->>'item_externo_id';
  END IF;
  FOR unit IN SELECT value FROM jsonb_array_elements(listing->'unidades') LOOP
   IF jsonb_typeof(unit->'dados_observados')='object' THEN
    UPDATE public.produto_anuncios SET dados_observados=dados_observados||(unit->'dados_observados')
     WHERE integration_id=p_account AND item_externo_id=listing->>'item_externo_id'
      AND coalesce(variacao_externa_id,'')=coalesce(unit->>'variacao_externa_id','');
   END IF;
  END LOOP;
 END LOOP;
 RETURN true;
END $$;
