-- Persist variation characteristics returned by the marketplace so staff can
-- identify a sellable unit without relying on its internal variation ID.
ALTER TABLE public.produto_anuncios
  ADD COLUMN IF NOT EXISTS atributos_variacao jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE OR REPLACE FUNCTION public.marketplace_catalog_sync_store_page(
  p_account integer,p_owner_token uuid,p_rows jsonb,p_checkpoint jsonb,p_complete boolean DEFAULT false
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE state public.marketplace_catalog_sync%ROWTYPE; listing jsonb; unit jsonb;
  header_id bigint; unit_id integer; external_id text; variation_id text;
BEGIN
  SELECT * INTO state FROM public.marketplace_catalog_sync
    WHERE account_id=p_account AND owner_token=p_owner_token AND lease_until>now() FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  FOR listing IN SELECT value FROM jsonb_array_elements(coalesce(p_rows,'[]'::jsonb)) LOOP
    external_id:=listing->>'item_externo_id';
    IF nullif(external_id,'') IS NULL THEN RAISE EXCEPTION 'INVALID_EXTERNAL_LISTING_ID' USING ERRCODE='22023'; END IF;
    INSERT INTO public.marketplace_anuncios(integration_id,item_externo_id,titulo,imagem_comercial,url,
      situacao_original,situacao_normalizada,user_product_id,familia_externa_id,catalogo_externo_id,
      provider_updated_at,collected_at,absent_since,last_seen_run_id)
    VALUES(p_account,external_id,listing->>'titulo',listing->>'imagem_comercial',listing->>'url',
      listing->>'situacao_original',listing->>'situacao_normalizada',listing->>'user_product_id',
      listing->>'familia_externa_id',listing->>'catalogo_externo_id',
      nullif(listing->>'provider_updated_at','')::timestamptz,now(),NULL,state.run_id)
    ON CONFLICT(integration_id,item_externo_id) DO UPDATE SET titulo=excluded.titulo,
      imagem_comercial=excluded.imagem_comercial,url=excluded.url,situacao_original=excluded.situacao_original,
      situacao_normalizada=excluded.situacao_normalizada,user_product_id=excluded.user_product_id,
      familia_externa_id=excluded.familia_externa_id,catalogo_externo_id=excluded.catalogo_externo_id,
      provider_updated_at=excluded.provider_updated_at,collected_at=now(),absent_since=NULL,last_seen_run_id=state.run_id
    RETURNING id INTO header_id;
    FOR unit IN SELECT value FROM jsonb_array_elements(coalesce(listing->'unidades','[]'::jsonb)) LOOP
      variation_id:=coalesce(unit->>'variacao_externa_id','');
      SELECT id INTO unit_id FROM public.produto_anuncios
        WHERE integration_id=p_account AND item_externo_id=external_id
          AND coalesce(variacao_externa_id,'')=variation_id ORDER BY id LIMIT 1 FOR UPDATE;
      IF unit_id IS NULL THEN
        INSERT INTO public.produto_anuncios(integration_id,item_externo_id,variacao_externa_id,anuncio_id,
          sku_externo,preco_observado,disponibilidade_observada,atributos_variacao)
        VALUES(p_account,external_id,nullif(variation_id,''),header_id,unit->>'sku_externo',
          nullif(unit->>'preco_observado','')::numeric,unit->>'disponibilidade_observada',
          coalesce(unit->'atributos_variacao','{}'::jsonb)) RETURNING id INTO unit_id;
      ELSE
        UPDATE public.produto_anuncios SET anuncio_id=header_id,sku_externo=unit->>'sku_externo',
          preco_observado=nullif(unit->>'preco_observado','')::numeric,
          disponibilidade_observada=unit->>'disponibilidade_observada',
          atributos_variacao=coalesce(unit->'atributos_variacao','{}'::jsonb) WHERE id=unit_id;
      END IF;
      unit_id:=NULL;
    END LOOP;
  END LOOP;
  IF p_complete THEN
    UPDATE public.marketplace_anuncios SET absent_since=coalesce(absent_since,now())
      WHERE integration_id=p_account AND last_seen_run_id IS DISTINCT FROM state.run_id;
    UPDATE public.marketplace_catalog_sync SET status='complete',checkpoint='{}',lease_until='-infinity',
      owner_token=NULL,last_complete_at=now(),error_code=NULL,updated_at=now() WHERE account_id=p_account;
  ELSE
    UPDATE public.marketplace_catalog_sync SET checkpoint=coalesce(p_checkpoint,'{}'),
      lease_until=now()+interval '5 minutes',updated_at=now() WHERE account_id=p_account;
  END IF;
  RETURN true;
END $$;

REVOKE ALL ON FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean)
  TO service_role;
