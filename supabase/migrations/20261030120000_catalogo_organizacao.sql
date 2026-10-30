-- Preserve variation attributes in the existing lease-protected transaction.
ALTER FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean)
 RENAME TO marketplace_catalog_sync_store_page_base;
REVOKE ALL ON FUNCTION public.marketplace_catalog_sync_store_page_base(integer,uuid,jsonb,jsonb,boolean) FROM PUBLIC,anon,authenticated,service_role;
CREATE FUNCTION public.marketplace_catalog_sync_store_page(p_account integer,p_owner_token uuid,p_rows jsonb,p_checkpoint jsonb,p_complete boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE listing jsonb; unit jsonb;
BEGIN
 IF NOT public.marketplace_catalog_sync_store_page_base(p_account,p_owner_token,p_rows,p_checkpoint,p_complete) THEN RETURN false; END IF;
 FOR listing IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
  FOR unit IN SELECT value FROM jsonb_array_elements(listing->'unidades') LOOP
   UPDATE public.produto_anuncios SET atributos_variacao=coalesce(unit->'atributos_variacao','{}'::jsonb)
   WHERE integration_id=p_account AND item_externo_id=listing->>'item_externo_id'
    AND coalesce(variacao_externa_id,'')=coalesce(unit->>'variacao_externa_id','');
  END LOOP;
 END LOOP;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_catalog_sync_store_page(integer,uuid,jsonb,jsonb,boolean) TO service_role;

CREATE TABLE public.catalogo_anuncio_familias(
 anuncio_id bigint PRIMARY KEY REFERENCES public.marketplace_anuncios(id),
 produto_pai_id integer REFERENCES public.produtos(id),motivo text,
 updated_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE public.catalogo_anuncio_familias ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.catalogo_anuncio_familias FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.catalogo_anuncio_familias TO service_role;

CREATE FUNCTION public.catalogo_organizar_anuncio(p_anuncio bigint,p_actor integer DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE header public.marketplace_anuncios%ROWTYPE; parent public.produtos%ROWTYPE;
 ids integer[]; parent_ids integer[]; target integer; axes jsonb; variants jsonb;
 reason text; result jsonb; created boolean:=false;
BEGIN
 -- Serialize family adoption against the existing family-depth guard.
 PERFORM pg_advisory_xact_lock(1250269001,1);
 SELECT * INTO header FROM public.marketplace_anuncios WHERE id=p_anuncio FOR UPDATE;
 IF NOT FOUND OR header.absent_since IS NOT NULL THEN RETURN jsonb_build_object('status','ignored'); END IF;
 PERFORM 1 FROM public.produto_anuncios WHERE anuncio_id=p_anuncio ORDER BY id FOR UPDATE;
 SELECT array_agg(DISTINCT produto_id) FILTER(WHERE produto_id IS NOT NULL) INTO ids FROM public.produto_anuncios WHERE anuncio_id=p_anuncio;
 IF coalesce(cardinality(ids),0)<2 THEN RETURN jsonb_build_object('status','ignored'); END IF;
 PERFORM 1 FROM public.produtos WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 SELECT array_agg(DISTINCT parent_id) FILTER(WHERE parent_id IS NOT NULL) INTO parent_ids FROM public.produtos WHERE id=ANY(ids);
 IF EXISTS(SELECT 1 FROM public.produto_anuncios WHERE anuncio_id=p_anuncio AND (produto_id IS NULL OR nullif(variacao_externa_id,'') IS NULL OR atributos_variacao IS NULL OR atributos_variacao='{}')) THEN reason:='Atributos ou vínculos incompletos';
 ELSIF cardinality(parent_ids)>1 THEN reason:='Produtos pertencem a famílias diferentes';
 ELSIF EXISTS(SELECT 1 FROM public.produtos WHERE id=ANY(ids) AND (papel_catalogo='modelo' OR atributos->>'catalog_merged_into' IS NOT NULL)) THEN reason:='Produto agregador ou consolidado';
 ELSIF (SELECT count(DISTINCT (tipo_material,categoria_id)) FROM public.produtos WHERE id=ANY(ids))>1 THEN reason:='Classificações incompatíveis';
 ELSIF EXISTS(SELECT 1 FROM public.produto_anuncios u JOIN public.produto_anuncios other ON other.produto_id=u.produto_id AND other.id<>u.id WHERE u.anuncio_id=p_anuncio AND (other.atributos_variacao IS NULL OR other.atributos_variacao='{}' OR other.atributos_variacao<>u.atributos_variacao)) THEN reason:='Opções incompatíveis ou incompletas entre anúncios';
 END IF;
 IF reason IS NULL AND EXISTS(SELECT 1 FROM public.produto_anuncios WHERE anuncio_id=p_anuncio GROUP BY atributos_variacao HAVING count(DISTINCT produto_id)>1) THEN reason:='Combinação duplicada'; END IF;
 IF reason IS NULL AND EXISTS(SELECT 1 FROM public.produto_anuncios WHERE anuncio_id=p_anuncio GROUP BY produto_id HAVING count(DISTINCT atributos_variacao)>1) THEN reason:='Produto representa combinações diferentes'; END IF;
 IF reason IS NULL AND EXISTS(SELECT 1 FROM public.produto_anuncios u CROSS JOIN LATERAL jsonb_each_text(u.atributos_variacao) kv WHERE u.anuncio_id=p_anuncio AND (nullif(btrim(kv.key),'') IS NULL OR nullif(btrim(kv.value),'') IS NULL)) THEN reason:='Valor de variação incompleto'; END IF;
 IF reason IS NOT NULL THEN
  INSERT INTO public.catalogo_anuncio_familias(anuncio_id,motivo) VALUES(p_anuncio,reason) ON CONFLICT(anuncio_id) DO UPDATE SET motivo=excluded.motivo,updated_at=now();
  RETURN jsonb_build_object('status','pending','reason',reason);
 END IF;
 target:=parent_ids[1];
 BEGIN
  IF target IS NULL THEN
   INSERT INTO public.produtos(nome,sku,status,papel_catalogo,formato,estrutura,tipo_material,categoria_id,unidade_medida_id,atributos)
     SELECT header.titulo,'FAM-ANUNCIO-'||p_anuncio,'inativo','modelo','com_variacao','simples',p.tipo_material,p.categoria_id,p.unidade_medida_id,
     jsonb_build_object('images',CASE WHEN header.imagem_comercial IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(header.imagem_comercial) END)
    FROM public.produtos p WHERE p.id=ids[1] RETURNING id INTO target;
   created:=true;
  END IF;
  SELECT * INTO parent FROM public.produtos WHERE id=target FOR UPDATE;
  SELECT coalesce(jsonb_agg(jsonb_build_object('name',name,'options',options)),'[]') INTO axes FROM (
   SELECT name,jsonb_agg(DISTINCT option_value) options FROM (
    SELECT kv.key name,kv.value option_value FROM public.produto_anuncios u CROSS JOIN LATERAL jsonb_each_text(u.atributos_variacao) kv WHERE u.anuncio_id=p_anuncio
    UNION ALL SELECT cfg->>'name',opt #>> '{}' FROM jsonb_array_elements(coalesce(parent.atributos->'variations_config','[]')) cfg CROSS JOIN LATERAL jsonb_array_elements(cfg->'options') opt
   ) options GROUP BY name
  ) grouped;
  IF EXISTS(SELECT 1 FROM public.produto_anuncios u WHERE u.anuncio_id=p_anuncio AND (SELECT count(*) FROM jsonb_object_keys(u.atributos_variacao))<>jsonb_array_length(axes)) THEN RAISE EXCEPTION 'Eixos de variação incompletos' USING ERRCODE='22023'; END IF;
  IF NOT created AND NOT EXISTS(SELECT 1 FROM public.produtos WHERE id=ANY(ids) AND parent_id IS DISTINCT FROM target)
   AND NOT EXISTS(SELECT 1 FROM public.produto_anuncios u JOIN public.produtos p ON p.id=u.produto_id WHERE u.anuncio_id=p_anuncio AND coalesce(p.atributos->'variation_values','{}')<>u.atributos_variacao) THEN
   result:=jsonb_build_object('status','unchanged','produto_pai_id',target);
  ELSE
   SELECT jsonb_agg(jsonb_build_object('produto_id',id,'variation_values',attrs)) INTO variants FROM (
    SELECT DISTINCT p.id,u.atributos_variacao attrs FROM public.produtos p JOIN public.produto_anuncios u ON u.produto_id=p.id WHERE u.anuncio_id=p_anuncio
   ) inputs;
   UPDATE public.produtos SET parent_id=target,papel_catalogo='variacao',formato='variacao',herdar_bom_pai=false,herdar_dados_pai=false WHERE id=ANY(ids) AND parent_id IS NULL;
   PERFORM public.catalogo_salvar_familia(target,parent.catalogo_versao,axes,variants,'{}'::integer[],NULL::uuid,p_actor);
   result:=jsonb_build_object('status',CASE WHEN created THEN 'created' ELSE 'extended' END,'produto_pai_id',target);
  END IF;
 EXCEPTION WHEN SQLSTATE '22023' OR unique_violation THEN
  reason:=SQLERRM;
  INSERT INTO public.catalogo_anuncio_familias(anuncio_id,motivo) VALUES(p_anuncio,reason) ON CONFLICT(anuncio_id) DO UPDATE SET motivo=excluded.motivo,updated_at=now();
  RETURN jsonb_build_object('status','pending','reason',reason);
 END;
 INSERT INTO public.catalogo_anuncio_familias(anuncio_id,produto_pai_id) VALUES(p_anuncio,target) ON CONFLICT(anuncio_id) DO UPDATE SET produto_pai_id=excluded.produto_pai_id,motivo=NULL,updated_at=now();
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.catalogo_organizar_anuncio(bigint,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.catalogo_organizar_anuncio(bigint,integer) TO service_role;
