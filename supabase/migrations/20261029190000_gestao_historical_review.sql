-- Explicit, expiring, actor-bound historical reassignment previews.
CREATE TABLE public.gestao_item_reprocessamentos (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),usuario_id integer NOT NULL,motivo text NOT NULL,
 scope jsonb NOT NULL,status text NOT NULL DEFAULT 'preview',expires_at timestamptz NOT NULL DEFAULT now()+interval '30 minutes',
 created_at timestamptz NOT NULL DEFAULT now(),finished_at timestamptz,error_code text,
 catalog_hash text NOT NULL,processed integer NOT NULL DEFAULT 0
);
CREATE TABLE public.gestao_item_reprocessamento_itens (
 request_id uuid NOT NULL REFERENCES public.gestao_item_reprocessamentos(id),
 fato_id bigint NOT NULL,pedido_id integer NOT NULL,before_row jsonb NOT NULL,
 produto_novo integer,anuncio_novo bigint,unidade_nova integer,origem_nova text NOT NULL,
 processed_at timestamptz,PRIMARY KEY(request_id,fato_id)
);
CREATE INDEX ON public.gestao_item_reprocessamento_itens(request_id,pedido_id) WHERE processed_at IS NULL;
ALTER TABLE public.gestao_item_reprocessamentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gestao_item_reprocessamento_itens ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.gestao_item_reprocessamentos,public.gestao_item_reprocessamento_itens FROM anon,authenticated;
GRANT SELECT ON public.gestao_item_reprocessamentos,public.gestao_item_reprocessamento_itens TO service_role;

CREATE FUNCTION public.gestao_item_catalog_hash(p_account integer) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT md5(jsonb_build_object(
  'products',(SELECT jsonb_agg(jsonb_build_array(id,sku,papel_catalogo) ORDER BY id) FROM produtos),
  'units',(SELECT jsonb_agg(jsonb_build_array(id,produto_id,vinculo_versao) ORDER BY id) FROM produto_anuncios WHERE integration_id=p_account),
  'aliases',(SELECT jsonb_agg(jsonb_build_array(id,produto_id,normalizado,aprovado) ORDER BY id) FROM produtos_externos WHERE integration_id=p_account)
 )::text);
$$;

CREATE FUNCTION public.gestao_item_reprocessamento_previa(p_actor integer,p_scope jsonb,p_motivo text)
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
       WHEN cardinality(candidates.ids)=1 THEN candidates.ids[1] END,
  unit.anuncio_id,unit.id,
  CASE WHEN unit.origem_vinculo IN ('manual','confirmado') THEN 'manual'
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
 WHERE o.account_id=account AND i.sold_on BETWEEN (p_scope->>'date_from')::date AND (p_scope->>'date_to')::date
  AND (p_scope->>'product_id' IS NULL OR i.produto_id=(p_scope->>'product_id')::integer)
  AND (p_scope->>'announcement_id' IS NULL OR i.anuncio_id=(p_scope->>'announcement_id')::bigint);
 SELECT count(DISTINCT pedido_id) INTO n FROM gestao_item_reprocessamento_itens WHERE request_id=token;
 RETURN jsonb_build_object('token',token,'orders',n,'scope',p_scope,'expires_at',now()+interval '30 minutes',
  'changed_items',(SELECT count(*) FROM gestao_item_reprocessamento_itens x WHERE x.request_id=token
    AND (x.before_row->>'produto_id')::integer IS DISTINCT FROM x.produto_novo));
END $$;

CREATE FUNCTION public.gestao_item_reprocessamento_confirmar(p_token uuid,p_actor integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE r gestao_item_reprocessamentos%ROWTYPE;
BEGIN
 SELECT * INTO r FROM gestao_item_reprocessamentos WHERE id=p_token AND usuario_id=p_actor FOR UPDATE;
 IF NOT FOUND OR r.status<>'preview' OR r.expires_at<=now() THEN
  RAISE EXCEPTION 'PREVIEW_EXPIRED_OR_ALREADY_USED' USING ERRCODE='22023';
 END IF;
 IF r.catalog_hash<>gestao_item_catalog_hash((r.scope->>'account_id')::integer) OR EXISTS(
  SELECT 1 FROM gestao_item_reprocessamento_itens x LEFT JOIN gestao_fatos_item i ON i.id=x.fato_id
  WHERE x.request_id=p_token AND (i.id IS NULL OR to_jsonb(i)<>x.before_row)) THEN
  RAISE EXCEPTION 'PREVIEW_CHANGED' USING ERRCODE='40001';
 END IF;
 UPDATE gestao_item_reprocessamentos SET status='queued' WHERE id=p_token;
 RETURN jsonb_build_object('request_id',p_token,'status','queued');
END $$;

CREATE FUNCTION public.gestao_item_reprocessamento_batch(p_token uuid,p_limit integer DEFAULT 25)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE r gestao_item_reprocessamentos%ROWTYPE; orders integer[]; n integer; more boolean;
BEGIN
 SELECT * INTO r FROM gestao_item_reprocessamentos WHERE id=p_token AND status IN ('queued','running') FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','inactive','has_more',false); END IF;
 SELECT array_agg(pedido_id) INTO orders FROM (SELECT DISTINCT pedido_id FROM gestao_item_reprocessamento_itens
  WHERE request_id=p_token AND processed_at IS NULL ORDER BY pedido_id LIMIT greatest(1,least(p_limit,100))) q;
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
 SELECT EXISTS(SELECT 1 FROM gestao_item_reprocessamento_itens WHERE request_id=p_token AND processed_at IS NULL) INTO more;
 n:=coalesce(cardinality(orders),0);
 UPDATE gestao_item_reprocessamentos SET processed=processed+n,status=CASE WHEN more THEN 'running' ELSE 'complete' END,
  finished_at=CASE WHEN more THEN NULL ELSE now() END WHERE id=p_token;
 RETURN jsonb_build_object('status',CASE WHEN more THEN 'running' ELSE 'complete' END,'processed',n,'has_more',more);
END $$;
REVOKE ALL ON FUNCTION public.gestao_item_catalog_hash(integer),
 public.gestao_item_reprocessamento_previa(integer,jsonb,text),public.gestao_item_reprocessamento_confirmar(uuid,integer),
 public.gestao_item_reprocessamento_batch(uuid,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.gestao_item_catalog_hash(integer),
 public.gestao_item_reprocessamento_previa(integer,jsonb,text),public.gestao_item_reprocessamento_confirmar(uuid,integer),
 public.gestao_item_reprocessamento_batch(uuid,integer) TO service_role;
