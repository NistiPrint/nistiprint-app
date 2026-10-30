-- Historical attribution changes only after a confirmed preview.
CREATE OR REPLACE FUNCTION public.gestao_item_reprocessamento_batch(p_token uuid,p_limit integer DEFAULT 25)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE r gestao_item_reprocessamentos%ROWTYPE; orders integer[]; n integer; more boolean;
BEGIN
 SELECT * INTO r FROM gestao_item_reprocessamentos WHERE id=p_token AND status IN ('queued','running') FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','inactive','has_more',false); END IF;
 SELECT array_agg(pedido_id) INTO orders FROM (SELECT DISTINCT pedido_id FROM gestao_item_reprocessamento_itens
  WHERE request_id=p_token AND processed_at IS NULL ORDER BY pedido_id LIMIT greatest(1,least(p_limit,100))) q;
 PERFORM 1 FROM produto_anuncios WHERE integration_id=(r.scope->>'account_id')::integer ORDER BY id FOR SHARE;
 PERFORM 1 FROM produtos ORDER BY id FOR SHARE;
 PERFORM 1 FROM produtos_externos WHERE integration_id=(r.scope->>'account_id')::integer ORDER BY id FOR SHARE;
 PERFORM 1 FROM gestao_outbox WHERE pedido_id=ANY(orders) ORDER BY pedido_id FOR UPDATE;
 PERFORM 1 FROM gestao_fatos_pedido WHERE pedido_id=ANY(orders) ORDER BY pedido_id FOR UPDATE;
 PERFORM 1 FROM gestao_fatos_item WHERE pedido_id=ANY(orders) ORDER BY id FOR UPDATE;
 IF r.catalog_hash<>gestao_item_catalog_hash((r.scope->>'account_id')::integer) OR EXISTS(
  SELECT 1 FROM gestao_item_reprocessamento_itens x LEFT JOIN gestao_fatos_item i ON i.id=x.fato_id
  WHERE x.request_id=p_token AND x.pedido_id=ANY(orders) AND (i.id IS NULL OR to_jsonb(i)<>x.before_row)) THEN
  UPDATE gestao_item_reprocessamentos SET status='failed',error_code='preview_changed',finished_at=now() WHERE id=p_token;
  RETURN jsonb_build_object('status','failed','has_more',false,'error_code','preview_changed');
 END IF;
 UPDATE gestao_fatos_item i SET produto_id=x.produto_novo,anuncio_id=x.anuncio_novo,
  unidade_anuncio_id=x.unidade_nova,origem_atribuicao=x.origem_nova,revisao=i.revisao+1,synced_at=now()
 FROM gestao_item_reprocessamento_itens x WHERE x.request_id=p_token AND x.pedido_id=ANY(orders) AND i.id=x.fato_id;
 UPDATE gestao_item_reprocessamento_itens SET processed_at=now() WHERE request_id=p_token AND pedido_id=ANY(orders);
 INSERT INTO public.gestao_outbox(pedido_id) SELECT unnest(orders)
 ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),lease_until='-infinity';
 SELECT EXISTS(SELECT 1 FROM gestao_item_reprocessamento_itens WHERE request_id=p_token AND processed_at IS NULL) INTO more;
 n:=coalesce(cardinality(orders),0);
 UPDATE gestao_item_reprocessamentos SET processed=processed+n,status=CASE WHEN more THEN 'running' ELSE 'complete' END,
  finished_at=CASE WHEN more THEN NULL ELSE now() END WHERE id=p_token;
 RETURN jsonb_build_object('status',CASE WHEN more THEN 'running' ELSE 'complete' END,'processed',n,'has_more',more);
END $$;

CREATE OR REPLACE FUNCTION public.gestao_catalog_changed()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE r jsonb; rows jsonb[]; pid integer; aid integer; key text;
BEGIN
 IF TG_TABLE_NAME='produto_anuncios' AND TG_OP='UPDATE' THEN
  IF (to_jsonb(OLD)->'produto_id') IS NOT DISTINCT FROM (to_jsonb(NEW)->'produto_id')
   AND (to_jsonb(OLD)->'item_externo_id') IS NOT DISTINCT FROM (to_jsonb(NEW)->'item_externo_id')
   AND (to_jsonb(OLD)->'variacao_externa_id') IS NOT DISTINCT FROM (to_jsonb(NEW)->'variacao_externa_id')
   AND (to_jsonb(OLD)->'integration_id') IS NOT DISTINCT FROM (to_jsonb(NEW)->'integration_id') THEN RETURN NULL; END IF;
 END IF;
 rows:=CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH r IN ARRAY rows LOOP
  pid:=CASE WHEN TG_TABLE_NAME='produtos' THEN (r->>'id')::integer ELSE (r->>'produto_id')::integer END;
  aid:=CASE WHEN TG_TABLE_NAME='installed_integrations' THEN (r->>'id')::integer ELSE (r->>'integration_id')::integer END;
  IF pid IS NULL AND aid IS NULL THEN CONTINUE; END IF;
  key:=coalesce(pid::text,'*')||':'||coalesce(aid::text,'*');
  INSERT INTO gestao_catalog_scopes(scope_key,produto_id,account_id) VALUES(key,pid,aid)
  ON CONFLICT(scope_key) DO UPDATE SET cursor_id=0,generation=nextval('gestao_generation_seq');
 END LOOP; RETURN NULL;
END $function$;

CREATE OR REPLACE FUNCTION public.gestao_item_reprocessamento_previa(p_actor integer,p_scope jsonb,p_motivo text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE token uuid; account integer:=(p_scope->>'account_id')::integer; n integer;
BEGIN
 IF account IS NULL OR nullif(btrim(p_motivo),'') IS NULL OR p_actor IS NULL
  OR NOT EXISTS(SELECT 1 FROM installed_integrations WHERE id=account)
  OR (p_scope->>'date_from')::date IS NULL OR (p_scope->>'date_to')::date IS NULL
  OR (p_scope->>'date_to')::date<(p_scope->>'date_from')::date
  OR (p_scope->>'date_to')::date-(p_scope->>'date_from')::date>730 THEN
  RAISE EXCEPTION 'INVALID_REPROCESSING_SCOPE' USING ERRCODE='22023';
 END IF;
 INSERT INTO gestao_item_reprocessamentos(usuario_id,motivo,scope,catalog_hash)
 VALUES(p_actor,btrim(p_motivo),p_scope,gestao_item_catalog_hash(account)) RETURNING id INTO token;
 INSERT INTO gestao_item_reprocessamento_itens(request_id,fato_id,pedido_id,before_row,
   produto_novo,anuncio_novo,unidade_nova,origem_nova)
 SELECT token,i.id,i.pedido_id,to_jsonb(i),
  CASE WHEN unit.origem_vinculo IN ('manual','confirmado') THEN unit.produto_id
       WHEN pending_alias.blocked THEN NULL
       WHEN cardinality(candidates.ids)=1 THEN candidates.ids[1] END,
  unit.anuncio_id,unit.id,
  CASE WHEN unit.origem_vinculo IN ('manual','confirmado') THEN 'manual'
       WHEN pending_alias.blocked THEN 'alias_pending'
       WHEN cardinality(candidates.ids)=1 THEN 'matched'
       WHEN cardinality(candidates.ids)>1 THEN 'conflict' ELSE 'unmapped' END
 FROM gestao_fatos_item i JOIN gestao_fatos_pedido o ON o.pedido_id=i.pedido_id
 LEFT JOIN produto_anuncios unit ON unit.integration_id=o.account_id AND
   unit.item_externo_id=split_part(i.chave_grupo,':',2) AND
   coalesce(unit.variacao_externa_id,'')=split_part(i.chave_grupo,':variation:',2)
   AND i.chave_grupo LIKE 'listing:%'
 LEFT JOIN LATERAL (
  SELECT min(lower(btrim(item->>'sku'))) AS sku FROM jsonb_array_elements(o.payload->'items') item
  WHERE CASE WHEN nullif(btrim(item->>'listing'),'') IS NOT NULL THEN
    'listing:'||btrim(item->>'listing')||':variation:'||coalesce(nullif(item->>'variation',''),'')
   WHEN nullif(btrim(item->>'sku'),'') IS NOT NULL THEN 'sku:'||lower(btrim(item->>'sku'))
   ELSE 'unidentified' END=i.chave_grupo
  HAVING count(DISTINCT lower(btrim(item->>'sku')))=1
 ) source ON true
 LEFT JOIN LATERAL (
  SELECT array_agg(DISTINCT candidate ORDER BY candidate) AS ids FROM (
   SELECT p.id AS candidate FROM produtos p WHERE p.papel_catalogo<>'modelo' AND lower(btrim(p.sku))=source.sku
   UNION SELECT alias.produto_id FROM produtos_externos alias JOIN produtos p ON p.id=alias.produto_id
    WHERE alias.integration_id=account AND alias.aprovado AND alias.tipo='SKU' AND alias.normalizado=source.sku AND p.papel_catalogo<>'modelo'
  ) c
 ) candidates ON true
 LEFT JOIN LATERAL (
  SELECT bool_or(alias.aprovado IS NOT TRUE OR p.papel_catalogo='modelo') AS blocked
  FROM produtos_externos alias JOIN produtos p ON p.id=alias.produto_id
  WHERE alias.integration_id=account AND alias.tipo='SKU' AND alias.normalizado=source.sku
 ) pending_alias ON true
 WHERE o.account_id=account AND i.sold_on BETWEEN (p_scope->>'date_from')::date AND (p_scope->>'date_to')::date
  AND (p_scope->>'product_id' IS NULL OR i.produto_id=(p_scope->>'product_id')::integer)
  AND (p_scope->>'announcement_id' IS NULL OR i.anuncio_id=(p_scope->>'announcement_id')::bigint);
 SELECT count(DISTINCT pedido_id) INTO n FROM gestao_item_reprocessamento_itens WHERE request_id=token;
 RETURN jsonb_build_object('token',token,'orders',n,'scope',p_scope,'expires_at',now()+interval '30 minutes',
  'changed_items',(SELECT count(*) FROM gestao_item_reprocessamento_itens x WHERE x.request_id=token
    AND (x.before_row->>'produto_id')::integer IS DISTINCT FROM x.produto_novo));
END $$;

