-- Snapshot de funcoes consultadas via MCP HTTP em 2026-10-29.
-- Evidencia de leitura; nao executar como migracao.

CREATE OR REPLACE FUNCTION public.catalog_validate_product_role()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE parent_product public.produtos%ROWTYPE;
BEGIN
  -- Older create/clone RPCs may only set parent_id. Normalize that legacy
  -- insert into the canonical role while preserving the single-level rule.
  IF NEW.parent_id IS NOT NULL AND NEW.papel_catalogo='individual' THEN
    NEW.papel_catalogo:='variacao';
  END IF;
  IF NEW.papel_catalogo='variacao' THEN
    IF NEW.parent_id IS NULL OR NEW.parent_id=NEW.id THEN
      RAISE EXCEPTION 'VARIATION_REQUIRES_MODEL_PARENT' USING ERRCODE='22023';
    END IF;
    SELECT * INTO parent_product FROM public.produtos WHERE id=NEW.parent_id FOR UPDATE;
    IF NOT FOUND OR parent_product.parent_id IS NOT NULL THEN
      RAISE EXCEPTION 'FAMILY_PARENT_MUST_BE_ROOT' USING ERRCODE='22023';
    END IF;
    IF parent_product.papel_catalogo<>'modelo' THEN
      UPDATE public.produtos SET papel_catalogo='modelo',formato='com_variacao'
        WHERE id=NEW.parent_id;
    END IF;
    NEW.formato:='variacao';
  ELSIF NEW.parent_id IS NOT NULL THEN
    RAISE EXCEPTION 'ONLY_VARIATIONS_CAN_HAVE_PARENT' USING ERRCODE='22023';
  ELSIF NEW.papel_catalogo IN ('individual','modelo') AND EXISTS(
      SELECT 1 FROM public.produtos child WHERE child.parent_id=NEW.id AND child.id<>NEW.id
        AND NEW.papel_catalogo<>'modelo') THEN
    RAISE EXCEPTION 'PRODUCT_WITH_VARIATIONS_MUST_REMAIN_MODEL' USING ERRCODE='22023';
  END IF;
  RETURN NEW;
END $function$
;

CREATE OR REPLACE FUNCTION public.catalogo_salvar_familia(p_produto_pai_id integer, p_expected_version integer, p_eixos jsonb, p_variacoes jsonb, p_inativar_ids integer[] DEFAULT '{}'::integer[], p_usuario uuid DEFAULT NULL::uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
  pai public.produtos%ROWTYPE;
  eixo jsonb;
  variacao jsonb;
  valores jsonb;
  v_produto_id integer;
  v_opcao_id bigint;
  v_eixo_id bigint;
  v_option jsonb;
  v_options jsonb;
  v_option_ids bigint[];
  v_option_name text;
  v_axis_name text;
  v_raw_values jsonb;
  v_normalized_axes jsonb:='[]'::jsonb;
  chave text;
  attrs jsonb;
  nome text;
  novo_id integer;
BEGIN
  SELECT * INTO pai FROM public.produtos WHERE id=p_produto_pai_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'PRODUCT_NOT_FOUND' USING ERRCODE='P0002'; END IF;
  IF pai.catalogo_versao<>p_expected_version THEN
    RAISE EXCEPTION 'CATALOG_VERSION_CONFLICT' USING ERRCODE='40001';
  END IF;
  IF pai.parent_id IS NOT NULL THEN RAISE EXCEPTION 'FAMILY_PARENT_MUST_BE_ROOT' USING ERRCODE='22023'; END IF;
  IF jsonb_typeof(p_eixos)<>'array' OR jsonb_typeof(p_variacoes)<>'array' THEN
    RAISE EXCEPTION 'INVALID_FAMILY_PAYLOAD' USING ERRCODE='22023';
  END IF;

  UPDATE public.produtos SET papel_catalogo='modelo',formato='com_variacao' WHERE id=p_produto_pai_id;
  DELETE FROM public.produto_pai_eixo_opcoes WHERE produto_pai_id=p_produto_pai_id;
  DELETE FROM public.produto_pai_eixos WHERE produto_pai_id=p_produto_pai_id;
  FOR eixo IN SELECT value FROM jsonb_array_elements(p_eixos) LOOP
    v_axis_name:=nullif(btrim(coalesce(eixo->>'nome',eixo->>'name')),'');
    IF nullif(eixo->>'eixo_id','') IS NOT NULL THEN
      v_eixo_id:=(eixo->>'eixo_id')::bigint;
      IF v_axis_name IS NULL THEN SELECT nome INTO v_axis_name FROM public.produto_eixos WHERE id=v_eixo_id; END IF;
    ELSE
      IF v_axis_name IS NULL THEN RAISE EXCEPTION 'AXIS_NAME_REQUIRED' USING ERRCODE='22023'; END IF;
       INSERT INTO public.produto_eixos(codigo,nome)
         VALUES('eixo_'||substr(md5(lower(btrim(v_axis_name))),1,24),v_axis_name)
        ON CONFLICT(nome) DO UPDATE SET nome=excluded.nome RETURNING id INTO v_eixo_id;
    END IF;
    INSERT INTO public.produto_pai_eixos(produto_pai_id,eixo_id,posicao)
      VALUES(p_produto_pai_id,v_eixo_id,coalesce((eixo->>'posicao')::integer,0));
    v_option_ids:='{}';
    v_options:=coalesce(eixo->'opcao_ids',eixo->'opcoes',eixo->'options');
    IF jsonb_typeof(v_options)<>'array' THEN RAISE EXCEPTION 'INVALID_AXIS_OPTIONS' USING ERRCODE='22023'; END IF;
    FOR v_option IN SELECT value FROM jsonb_array_elements(v_options) LOOP
      IF jsonb_typeof(v_options->0)='number' OR eixo ? 'opcao_ids' THEN
        v_opcao_id:=v_option::text::bigint;
      ELSE
        v_option_name:=nullif(btrim(v_option #>> '{}'),'');
        IF v_option_name IS NULL THEN RAISE EXCEPTION 'OPTION_NAME_REQUIRED' USING ERRCODE='22023'; END IF;
         INSERT INTO public.produto_eixo_opcoes(eixo_id,codigo,nome)
           VALUES(v_eixo_id,'opcao_'||v_eixo_id::text||'_'||substr(md5(lower(btrim(v_option_name))),1,16),v_option_name)
          ON CONFLICT(eixo_id,nome) DO UPDATE SET nome=excluded.nome RETURNING id INTO v_opcao_id;
      END IF;
      INSERT INTO public.produto_pai_eixo_opcoes(produto_pai_id,eixo_id,opcao_id)
        VALUES(p_produto_pai_id,v_eixo_id,v_opcao_id);
      v_option_ids:=array_append(v_option_ids,v_opcao_id);
    END LOOP;
    v_normalized_axes:=v_normalized_axes||jsonb_build_array(jsonb_build_object(
      'eixo_id',v_eixo_id,'opcao_ids',to_jsonb(v_option_ids),'posicao',coalesce((eixo->>'posicao')::integer,0)));
  END LOOP;
  UPDATE public.produtos p SET atributos=jsonb_set(coalesce(p.atributos,'{}'::jsonb),'{variations_config}',coalesce((
    SELECT jsonb_agg(jsonb_build_object('name',axis.nome,'options',coalesce((
      SELECT jsonb_agg(opt.nome ORDER BY opt.nome) FROM public.produto_pai_eixo_opcoes allowed
      JOIN public.produto_eixo_opcoes opt ON opt.id=allowed.opcao_id
      WHERE allowed.produto_pai_id=p_produto_pai_id AND allowed.eixo_id=axis.id),'[]'::jsonb)) ORDER BY family_axis.posicao)
    FROM public.produto_pai_eixos family_axis JOIN public.produto_eixos axis ON axis.id=family_axis.eixo_id
    WHERE family_axis.produto_pai_id=p_produto_pai_id),'[]'::jsonb),true)
    WHERE p.id=p_produto_pai_id;

  UPDATE public.produtos SET status='inativo',catalogo_inativado_em=now()
    WHERE id=ANY(coalesce(p_inativar_ids,'{}')) AND parent_id=p_produto_pai_id;
  IF EXISTS(SELECT 1 FROM unnest(coalesce(p_inativar_ids,'{}')) i
      WHERE NOT EXISTS(SELECT 1 FROM public.produtos p WHERE p.id=i AND p.parent_id=p_produto_pai_id)) THEN
    RAISE EXCEPTION 'VARIATION_NOT_IN_FAMILY' USING ERRCODE='22023';
  END IF;

  FOR variacao IN SELECT value FROM jsonb_array_elements(p_variacoes) LOOP
    v_produto_id:=nullif(variacao->>'produto_id','')::integer;
    valores:=coalesce(variacao->'valores','[]'::jsonb);
    IF jsonb_typeof(variacao->'valores') IS DISTINCT FROM 'array' THEN
      v_raw_values:=coalesce(variacao->'variation_values',variacao->'atributos'->'variation_values','{}'::jsonb);
      valores:='[]'::jsonb;
      FOR eixo IN SELECT value FROM jsonb_array_elements(v_normalized_axes) LOOP
        SELECT nome INTO v_axis_name FROM public.produto_eixos WHERE id=(eixo->>'eixo_id')::bigint;
        v_option_name:=nullif(btrim(v_raw_values->>v_axis_name),'');
        IF v_option_name IS NOT NULL THEN
          SELECT id INTO v_opcao_id FROM public.produto_eixo_opcoes
            WHERE eixo_id=(eixo->>'eixo_id')::bigint AND lower(btrim(nome))=lower(v_option_name) LIMIT 1;
          IF v_opcao_id IS NULL OR NOT v_opcao_id=ANY(ARRAY(SELECT value::text::bigint FROM jsonb_array_elements(eixo->'opcao_ids'))) THEN
            RAISE EXCEPTION 'OPTION_NOT_ALLOWED_IN_FAMILY' USING ERRCODE='22023';
          END IF;
          valores:=valores||jsonb_build_array(jsonb_build_object('eixo_id',(eixo->>'eixo_id')::bigint,'opcao_id',v_opcao_id));
        END IF;
      END LOOP;
    END IF;
    -- Recompute after legacy name/value payloads have been translated. The
    -- incoming JSON may not contain canonical IDs yet.
    chave:='';
    FOR eixo IN SELECT value FROM jsonb_array_elements(v_normalized_axes)
      ORDER BY (value->>'eixo_id')::bigint LOOP
      v_eixo_id:=(eixo->>'eixo_id')::bigint;
      SELECT (v->>'opcao_id')::bigint INTO v_opcao_id FROM jsonb_array_elements(valores) v
        WHERE (v->>'eixo_id')::bigint=v_eixo_id;
      IF v_opcao_id IS NULL OR NOT EXISTS(SELECT 1 FROM public.produto_pai_eixo_opcoes allowed
          WHERE allowed.produto_pai_id=p_produto_pai_id AND allowed.eixo_id=v_eixo_id AND allowed.opcao_id=v_opcao_id) THEN
        chave:=NULL; EXIT;
      END IF;
      chave:=concat_ws('|',nullif(chave,''),v_eixo_id||':'||v_opcao_id);
    END LOOP;
    IF (SELECT count(*) FROM jsonb_array_elements(valores)) <>
       (SELECT count(DISTINCT value->>'eixo_id') FROM jsonb_array_elements(valores)) THEN
      RAISE EXCEPTION 'DUPLICATE_VARIATION_AXIS' USING ERRCODE='22023';
    END IF;
    IF v_produto_id IS NULL THEN
      IF nullif(btrim(variacao->>'sku'),'') IS NULL THEN RAISE EXCEPTION 'SKU_REQUIRED' USING ERRCODE='22023'; END IF;
      nome:=coalesce(nullif(btrim(variacao->>'nome'),''),pai.nome||' - '||coalesce(chave,'Rascunho'));
      INSERT INTO public.produtos(sku,nome,descricao,categoria_id,tags,atributos,precificacao,dados_estoque,
          preco_custo,preco_venda,estoque_minimo,estoque_maximo,tipo_material,unidade_medida_id,parent_id,
          status,formato,papel_catalogo,estrutura,herdar_dados_pai,herdar_bom_pai)
      VALUES(btrim(variacao->>'sku'),nome,coalesce(variacao->>'descricao',pai.descricao),
          coalesce(nullif(variacao->>'categoria_id','')::integer,pai.categoria_id),pai.tags,
          coalesce(pai.atributos,'{}'::jsonb)||jsonb_build_object('variation_values','{}'::jsonb),
          coalesce(pai.precificacao,'{}'::jsonb),coalesce(pai.dados_estoque,'{}'::jsonb),
          coalesce(nullif(variacao->>'preco_custo','')::numeric,pai.preco_custo),
          coalesce(nullif(variacao->>'preco_venda','')::numeric,pai.preco_venda),
          coalesce(nullif(variacao->>'estoque_minimo','')::integer,0),coalesce(nullif(variacao->>'estoque_maximo','')::integer,0),
          coalesce(nullif(variacao->>'tipo_material',''),pai.tipo_material),
          coalesce(nullif(variacao->>'unidade_medida_id','')::integer,pai.unidade_medida_id),p_produto_pai_id,
          coalesce(variacao->>'status','rascunho'),'variacao','variacao',pai.estrutura,true,true)
      RETURNING id INTO v_produto_id;
    ELSE
      UPDATE public.produtos SET papel_catalogo='variacao',formato='variacao',status=coalesce(variacao->>'status',status),
        sku=coalesce(nullif(btrim(variacao->>'sku'),''),sku),nome=coalesce(nullif(btrim(variacao->>'nome'),''),nome),
        parent_id=p_produto_pai_id WHERE id=v_produto_id AND parent_id=p_produto_pai_id;
      IF NOT FOUND THEN RAISE EXCEPTION 'VARIATION_NOT_IN_FAMILY' USING ERRCODE='22023'; END IF;
    END IF;
    DELETE FROM public.produto_variacao_valores WHERE produto_variacao_valores.produto_id=v_produto_id;
    FOR eixo IN SELECT value FROM jsonb_array_elements(valores) LOOP
      IF NOT EXISTS(SELECT 1 FROM public.produto_pai_eixo_opcoes x
          WHERE x.produto_pai_id=p_produto_pai_id
            AND x.eixo_id=(eixo->>'eixo_id')::bigint
            AND x.opcao_id=(eixo->>'opcao_id')::bigint) THEN
        RAISE EXCEPTION 'OPTION_NOT_ALLOWED_IN_FAMILY' USING ERRCODE='22023';
      END IF;
      INSERT INTO public.produto_variacao_valores(produto_id,eixo_id,opcao_id,combinacao_chave)
      VALUES(v_produto_id,(eixo->>'eixo_id')::bigint,(eixo->>'opcao_id')::bigint,chave);
    END LOOP;
    IF coalesce(variacao->>'status','rascunho')='ativo'
       AND ((SELECT count(*) FROM jsonb_array_elements(v_normalized_axes))=0
         OR chave IS NULL OR nullif(chave,'') IS NULL
         OR jsonb_array_length(valores)<>(SELECT count(*) FROM jsonb_array_elements(v_normalized_axes))) THEN
      RAISE EXCEPTION 'ACTIVE_VARIATION_REQUIRES_COMPLETE_COMBINATION' USING ERRCODE='22023';
    END IF;
    IF chave IS NOT NULL AND jsonb_array_length(valores)=(SELECT count(*) FROM jsonb_array_elements(v_normalized_axes)) THEN
      INSERT INTO public.produto_variacao_combinacoes(produto_id,produto_pai_id,combinacao_chave)
        VALUES(v_produto_id,p_produto_pai_id,chave)
        ON CONFLICT(produto_id) DO UPDATE SET produto_pai_id=excluded.produto_pai_id,combinacao_chave=excluded.combinacao_chave;
    ELSE
      DELETE FROM public.produto_variacao_combinacoes WHERE produto_variacao_combinacoes.produto_id=v_produto_id;
    END IF;
    SELECT coalesce(jsonb_object_agg(e.nome,o.nome),'{}'::jsonb) INTO attrs
      FROM public.produto_variacao_valores v JOIN public.produto_eixos e ON e.id=v.eixo_id
      JOIN public.produto_eixo_opcoes o ON o.id=v.opcao_id WHERE v.produto_id=v_produto_id;
    UPDATE public.produtos SET atributos=coalesce(atributos,'{}'::jsonb)||jsonb_build_object('variation_values',coalesce(attrs,'{}'::jsonb))
      WHERE id=v_produto_id;
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM public.produtos v
    WHERE v.parent_id=p_produto_pai_id AND v.status='ativo'
      AND ((SELECT count(*) FROM public.produto_pai_eixos pe WHERE pe.produto_pai_id=p_produto_pai_id)=0
        OR (SELECT count(*) FROM public.produto_pai_eixos pe WHERE pe.produto_pai_id=p_produto_pai_id)
           <>(SELECT count(*) FROM public.produto_variacao_valores vv WHERE vv.produto_id=v.id)
        OR EXISTS(SELECT 1 FROM public.produto_variacao_valores vv
          WHERE vv.produto_id=v.id AND NOT EXISTS(SELECT 1 FROM public.produto_pai_eixo_opcoes allowed
            WHERE allowed.produto_pai_id=p_produto_pai_id AND allowed.eixo_id=vv.eixo_id AND allowed.opcao_id=vv.opcao_id)))
  ) THEN RAISE EXCEPTION 'ACTIVE_VARIATION_INVALIDATED_BY_FAMILY_CHANGE' USING ERRCODE='22023'; END IF;
  UPDATE public.produtos SET catalogo_versao=catalogo_versao+1 WHERE id=p_produto_pai_id RETURNING catalogo_versao INTO novo_id;
  RETURN jsonb_build_object('produto_pai_id',p_produto_pai_id,'catalogo_versao',novo_id);
END $function$
;

CREATE OR REPLACE FUNCTION public.gestao_backfill_order_item_facts(p_after integer DEFAULT 0, p_limit integer DEFAULT 100)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE processed integer; next_after integer;
BEGIN
  WITH batch AS (
    SELECT pedido_id FROM public.gestao_fatos_pedido WHERE pedido_id>greatest(0,p_after)
    ORDER BY pedido_id LIMIT greatest(1,least(p_limit,500))
  ), updated AS (
    UPDATE public.gestao_fatos_pedido source SET synced_at=now()
    FROM batch WHERE source.pedido_id=batch.pedido_id
    RETURNING source.pedido_id
  ) SELECT count(*)::integer,max(pedido_id) INTO processed,next_after FROM updated;
  RETURN jsonb_build_object('processed',coalesce(processed,0),'next_after',coalesce(next_after,p_after),
    'has_more',EXISTS(SELECT 1 FROM public.gestao_fatos_pedido WHERE pedido_id>coalesce(next_after,p_after)));
END $function$
;

CREATE OR REPLACE FUNCTION public.gestao_collection_lease(p_account integer, p_capability text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$ BEGIN
  INSERT INTO gestao_coletas(account_id,capability,status) VALUES(p_account,p_capability,'pending') ON CONFLICT DO NOTHING;
  UPDATE gestao_coletas SET lease_until=now()+interval '5 minutes'
  WHERE account_id=p_account AND capability=p_capability AND lease_until<now();
  RETURN FOUND;
END $function$
;

CREATE OR REPLACE FUNCTION public.gestao_desempenho(p_start date, p_end date, p_filters jsonb DEFAULT '{}'::jsonb, p_group_by text DEFAULT 'produto'::text, p_limit integer DEFAULT 100, p_offset integer DEFAULT 0)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE result jsonb;
BEGIN
  IF p_end<p_start OR p_group_by NOT IN ('plataforma','conta','modelo','produto','anuncio','variacao') THEN
    RAISE EXCEPTION 'INVALID_PERFORMANCE_FILTERS' USING ERRCODE='22023';
  END IF;
  WITH selected AS (
    SELECT i.*,o.account_id,o.marketplace,o.payload->>'stage' AS order_stage,
      coalesce((o.payload->>'eligible')::boolean,false) AS eligible,
      coalesce(p.parent_id,p.id) AS modelo_id,
      coalesce(NULLIF(p.nome,''),ma.titulo,i.chave_grupo,'Não identificado') AS produto_nome,
      a.instance_name,
      CASE p_group_by
        WHEN 'plataforma' THEN coalesce(o.marketplace,'desconhecida')
        WHEN 'conta' THEN coalesce(o.account_id::text,'sem_conta')
        WHEN 'modelo' THEN coalesce(coalesce(p.parent_id,p.id)::text,i.chave_grupo)
        WHEN 'anuncio' THEN coalesce(i.anuncio_id::text,i.chave_grupo)
        WHEN 'variacao' THEN coalesce(i.unidade_anuncio_id::text,i.chave_grupo)
        ELSE coalesce(i.produto_id::text,i.chave_grupo)
      END AS group_key,
      CASE p_group_by
        WHEN 'plataforma' THEN coalesce(o.marketplace,'Plataforma desconhecida')
        WHEN 'conta' THEN coalesce(a.instance_name,o.account_id::text,'Sem conta')
        WHEN 'modelo' THEN coalesce(model.nome,p.nome,'Produto não identificado')
        WHEN 'anuncio' THEN coalesce(ma.titulo,ma.item_externo_id,'Anúncio não identificado')
        WHEN 'variacao' THEN coalesce(i.chave_grupo,'Variação não identificada')
        ELSE coalesce(p.nome,'Produto não identificado')
      END AS group_label
    FROM public.gestao_fatos_item i
    JOIN public.gestao_fatos_pedido o ON o.pedido_id=i.pedido_id
    LEFT JOIN public.produtos p ON p.id=i.produto_id
    LEFT JOIN public.produtos model ON model.id=coalesce(p.parent_id,p.id)
    LEFT JOIN public.marketplace_anuncios ma ON ma.id=i.anuncio_id
    LEFT JOIN public.installed_integrations a ON a.id=o.account_id
    WHERE i.sold_on BETWEEN p_start AND p_end
      AND (p_filters->>'platform' IS NULL OR lower(o.marketplace)=lower(p_filters->>'platform'))
      AND (p_filters->>'account_id' IS NULL OR o.account_id=(p_filters->>'account_id')::integer)
      AND (p_filters->>'model_id' IS NULL OR coalesce(p.parent_id,p.id)=(p_filters->>'model_id')::integer)
      AND (p_filters->>'product_id' IS NULL OR i.produto_id=(p_filters->>'product_id')::integer)
      AND (p_filters->>'announcement_id' IS NULL OR i.anuncio_id=(p_filters->>'announcement_id')::bigint)
  ), grouped AS (
    SELECT group_key,group_label,currency,count(DISTINCT pedido_id) FILTER(WHERE eligible) AS orders,
      sum(subtotal) FILTER(WHERE eligible) AS sales,sum(quantidade) FILTER(WHERE eligible) AS units,
      count(*) FILTER(WHERE eligible) AS item_groups,
      count(subtotal) FILTER(WHERE eligible) AS known_subtotals
    FROM selected GROUP BY group_key,group_label,currency
  ), sales_currency AS (
    SELECT currency,sum(subtotal) AS sales FROM selected WHERE eligible GROUP BY currency
  ), totals AS (
    SELECT count(DISTINCT pedido_id) FILTER(WHERE eligible) AS orders,
      CASE WHEN (SELECT count(*) FROM sales_currency)<=1 THEN sum(subtotal) FILTER(WHERE eligible) ELSE NULL END AS sales,
      sum(quantidade) FILTER(WHERE eligible) AS units,
      count(*) FILTER(WHERE eligible) AS item_groups,
      count(subtotal) FILTER(WHERE eligible) AS known_subtotals,
      (SELECT count(*) FROM sales_currency) AS currency_count,
      (SELECT jsonb_agg(jsonb_build_object('currency',coalesce(currency,'desconhecida'),'sales',sales)) FROM sales_currency) AS sales_by_currency,
      count(DISTINCT pedido_id) FILTER(WHERE order_stage IN ('cancelled','canceled')) AS cancellations,
      count(DISTINCT pedido_id) FILTER(WHERE order_stage IN ('returned','partially_returned')) AS returns,
      count(DISTINCT pedido_id) FILTER(WHERE order_stage IN ('refunded','partially_refunded')) AS refunds
    FROM selected
  ), series AS (
    SELECT sold_on AS day,currency,count(DISTINCT pedido_id) FILTER(WHERE eligible) AS orders,
      sum(subtotal) FILTER(WHERE eligible) AS sales,sum(quantidade) FILTER(WHERE eligible) AS units
    FROM selected GROUP BY sold_on,currency ORDER BY sold_on,currency
  ), traffic AS (
    SELECT jsonb_agg(jsonb_build_object('account_id',m.account_id,'announcement_id',ma.id,
      'resource_id',m.resource_id,'day',m.periodo_inicio,'kind',m.kind,'metrics',m.metrics,
      'orders',CASE WHEN ma.id IS NULL THEN NULL ELSE (SELECT count(DISTINCT i.pedido_id)
        FROM public.gestao_fatos_item i JOIN public.gestao_fatos_pedido o ON o.pedido_id=i.pedido_id
        WHERE i.anuncio_id=ma.id AND i.sold_on=m.periodo_inicio AND o.account_id=m.account_id
          AND coalesce((o.payload->>'eligible')::boolean,false)) END,
      'order_visit_rate',CASE WHEN m.kind='visits' AND nullif(m.metrics->>'visits','') IS NOT NULL
          AND (m.metrics->>'visits')::numeric>0 AND ma.id IS NOT NULL THEN round(100.0*(SELECT count(DISTINCT i.pedido_id)
            FROM public.gestao_fatos_item i JOIN public.gestao_fatos_pedido o ON o.pedido_id=i.pedido_id
            WHERE i.anuncio_id=ma.id AND i.sold_on=m.periodo_inicio AND o.account_id=m.account_id
              AND coalesce((o.payload->>'eligible')::boolean,false))/(m.metrics->>'visits')::numeric,2) END,
      'partial',m.parcial,'semantica',m.semantica,'source',m.source)
      ORDER BY m.periodo_inicio,ma.id) AS rows,max(m.collected_at) AS updated_at
    FROM public.gestao_metricas_anuncio_periodo m
    LEFT JOIN public.marketplace_anuncios ma ON ma.integration_id=m.account_id AND ma.item_externo_id=m.resource_id
    WHERE m.periodo_inicio BETWEEN p_start AND p_end
      AND m.semantica='diaria'
      AND (p_filters->>'account_id' IS NULL OR m.account_id=(p_filters->>'account_id')::integer)
      AND (p_filters->>'announcement_id' IS NULL OR ma.id=(p_filters->>'announcement_id')::bigint)
      AND (p_filters->>'platform' IS NULL OR EXISTS(SELECT 1 FROM public.installed_integrations ai
        WHERE ai.id=m.account_id AND lower(coalesce(ai.platform_slug,ai.module_id))=lower(p_filters->>'platform')))
      AND (p_filters->>'product_id' IS NULL OR EXISTS(SELECT 1 FROM public.produto_anuncios pa
        WHERE pa.anuncio_id=ma.id AND pa.produto_id=(p_filters->>'product_id')::integer))
      AND (p_filters->>'model_id' IS NULL OR EXISTS(SELECT 1 FROM public.produto_anuncios pa
        JOIN public.produtos linked ON linked.id=pa.produto_id
        WHERE pa.anuncio_id=ma.id AND coalesce(linked.parent_id,linked.id)=(p_filters->>'model_id')::integer))
  )
  SELECT jsonb_build_object(
    'rows',coalesce((SELECT jsonb_agg(to_jsonb(page_row)) FROM (
      SELECT * FROM grouped ORDER BY sales DESC NULLS LAST,group_label,currency LIMIT greatest(1,least(p_limit,500)) OFFSET greatest(0,p_offset)
    ) page_row),'[]'::jsonb),
    'totals',(SELECT to_jsonb(totals) FROM totals),
    'series',coalesce((SELECT jsonb_agg(to_jsonb(series)) FROM series),'[]'::jsonb),
    'traffic',coalesce((SELECT rows FROM traffic),'[]'::jsonb),
    'coverage',(SELECT jsonb_build_object('item_groups',item_groups,'known_subtotals',known_subtotals,
      'subtotal_percent',round(100.0*known_subtotals/nullif(item_groups,0),2)) FROM totals),
    'updated_at',greatest((SELECT max(synced_at) FROM public.gestao_fatos_item WHERE sold_on BETWEEN p_start AND p_end),
      (SELECT updated_at FROM traffic)),
    'group_by',p_group_by,
    'definitions',jsonb_build_object('sales','Subtotal conhecido das mercadorias em pedidos elegíveis.',
      'orders','Contagem distinta de pedidos elegíveis.','units','Quantidade conhecida em pedidos elegíveis.',
      'traffic','Métricas diárias por anúncio; não são distribuídas entre variações.')) INTO result;
  RETURN result;
END $function$
;

CREATE OR REPLACE FUNCTION public.gestao_materialize_item_facts()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE next_revision integer;
BEGIN
  SELECT coalesce(max(revisao),0)+1 INTO next_revision FROM public.gestao_fatos_item WHERE pedido_id=NEW.pedido_id;
  INSERT INTO public.gestao_fatos_item(pedido_id,chave_grupo,produto_id,anuncio_id,unidade_anuncio_id,
      origem_atribuicao,quantidade,subtotal,currency,sold_on,revisao)
  SELECT NEW.pedido_id,g.chave_grupo,g.produto_id,g.anuncio_id,g.unidade_anuncio_id,
      g.origem_atribuicao,g.quantidade,g.subtotal,nullif(upper(NEW.payload->>'currency'),''),NEW.sold_on,next_revision
  FROM (
    SELECT CASE
        WHEN nullif(btrim(item->>'listing'),'') IS NOT NULL
          THEN 'listing:'||btrim(item->>'listing')||':variation:'||coalesce(nullif(item->>'variation',''),'')
        WHEN nullif(btrim(item->>'sku'),'') IS NOT NULL
          THEN 'sku:'||lower(btrim(item->>'sku'))
        ELSE 'unidentified'
      END AS chave_grupo,
      CASE WHEN count(DISTINCT nullif(item->>'product_id',''))<=1
        THEN min(nullif(item->>'product_id','')::integer) ELSE NULL END AS produto_id,
      max(nullif(item->>'announcement_id','')::bigint) AS anuncio_id,
      max(nullif(item->>'listing_unit_id','')::integer) AS unidade_anuncio_id,
      CASE WHEN count(DISTINCT nullif(item->>'product_id',''))>1 OR count(DISTINCT item->>'mapping')<>1
        THEN 'conflict' ELSE max(item->>'mapping') END AS origem_atribuicao,
      CASE WHEN bool_or(nullif(item->>'quantity','') IS NOT NULL)
        THEN sum(nullif(item->>'quantity','')::numeric) ELSE NULL END AS quantidade,
      CASE WHEN bool_and(nullif(item->>'subtotal','') IS NOT NULL)
        THEN sum((item->>'subtotal')::numeric) ELSE NULL END AS subtotal
    FROM jsonb_array_elements(coalesce(NEW.payload->'items','[]'::jsonb)) item
    GROUP BY 1
  ) g
  ON CONFLICT(pedido_id,chave_grupo) DO UPDATE SET
      quantidade=excluded.quantidade,subtotal=excluded.subtotal,currency=excluded.currency,sold_on=excluded.sold_on,
    revisao=excluded.revisao,synced_at=now();
  -- Retain an item's first audited attribution through ordinary order refreshes.
  -- A deliberate historical remap uses gestao_replace_item_facts instead.
  DELETE FROM public.gestao_fatos_item old
  WHERE old.pedido_id=NEW.pedido_id AND NOT EXISTS(
    SELECT 1 FROM (
      SELECT CASE
          WHEN nullif(btrim(item->>'listing'),'') IS NOT NULL
            THEN 'listing:'||btrim(item->>'listing')||':variation:'||coalesce(nullif(item->>'variation',''),'')
          WHEN nullif(btrim(item->>'sku'),'') IS NOT NULL THEN 'sku:'||lower(btrim(item->>'sku'))
          ELSE 'unidentified'
        END AS chave_grupo
      FROM jsonb_array_elements(coalesce(NEW.payload->'items','[]'::jsonb)) item
      GROUP BY 1
    ) current_groups WHERE current_groups.chave_grupo=old.chave_grupo
  );
  RETURN NULL;
END $function$
;

CREATE OR REPLACE FUNCTION public.marketplace_catalog_sync_claim(p_account integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE result jsonb;
BEGIN
  INSERT INTO public.marketplace_catalog_sync(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
  UPDATE public.marketplace_catalog_sync SET owner_token=gen_random_uuid(),lease_until=now()+interval '5 minutes',
      run_id=CASE WHEN status IN ('idle','complete','unavailable') THEN gen_random_uuid() ELSE run_id END,
      checkpoint=CASE WHEN status IN ('idle','complete','unavailable') THEN '{}'::jsonb ELSE checkpoint END,
      status='running',error_code=NULL,updated_at=now()
    WHERE account_id=p_account AND lease_until<now()
    RETURNING jsonb_build_object('status',status,'owner_token',owner_token,'run_id',run_id,'checkpoint',checkpoint) INTO result;
  RETURN coalesce(result,jsonb_build_object('status','busy'));
END $function$
;

CREATE OR REPLACE FUNCTION public.marketplace_catalog_sync_fail(p_account integer, p_owner_token uuid, p_error text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$ BEGIN
  UPDATE public.marketplace_catalog_sync SET status='failed',error_code=p_error,owner_token=NULL,
    lease_until='-infinity',updated_at=now() WHERE account_id=p_account AND owner_token=p_owner_token;
  RETURN FOUND;
END $function$
;

CREATE OR REPLACE FUNCTION public.marketplace_catalog_sync_store_page(p_account integer, p_owner_token uuid, p_rows jsonb, p_checkpoint jsonb, p_complete boolean DEFAULT false)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
END $function$
;