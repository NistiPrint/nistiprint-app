-- Store only fields explicitly observed in the provider's successful response.
ALTER TABLE public.marketplace_anuncios ADD COLUMN IF NOT EXISTS dados_observados jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.produto_anuncios ADD COLUMN IF NOT EXISTS dados_observados jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean)
 RENAME TO marketplace_catalog_sync_store_page_observed_base;
REVOKE ALL ON FUNCTION public.marketplace_catalog_sync_store_page_observed_base(integer,uuid,jsonb,jsonb,boolean) FROM PUBLIC,anon,authenticated,service_role;
CREATE FUNCTION public.marketplace_catalog_sync_store_page(p_account integer,p_owner_token uuid,p_rows jsonb,p_checkpoint jsonb,p_complete boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE listing jsonb; unit jsonb;
BEGIN
 IF NOT public.marketplace_catalog_sync_store_page_observed_base(p_account,p_owner_token,p_rows,p_checkpoint,p_complete) THEN RETURN false; END IF;
 FOR listing IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
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
REVOKE ALL ON FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean) TO service_role;
