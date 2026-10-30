-- Never compare Sao Paulo commercial days with traffic buckets from another calendar.
CREATE OR REPLACE FUNCTION public.gestao_desempenho(
  p_start date,p_end date,p_filters jsonb,p_group_by text,
  p_limit integer,p_offset integer,p_sort text,p_direction text
) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
  IF p_sort NOT IN ('sales','orders','units','group_label') OR p_direction NOT IN ('asc','desc') THEN
    RAISE EXCEPTION 'INVALID_PERFORMANCE_SORT' USING ERRCODE='22023';
  END IF;
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
      'resource_id',m.resource_id,'day',m.periodo_inicio,'kind',m.kind,'metrics',m.metrics,'fuso_origem',m.fuso_origem,
      'orders',CASE WHEN ma.id IS NULL OR m.fuso_origem IS DISTINCT FROM 'America/Sao_Paulo' THEN NULL ELSE (SELECT count(DISTINCT i.pedido_id)
        FROM public.gestao_fatos_item i JOIN public.gestao_fatos_pedido o ON o.pedido_id=i.pedido_id
        WHERE i.anuncio_id=ma.id AND i.sold_on=m.periodo_inicio AND o.account_id=m.account_id
          AND coalesce((o.payload->>'eligible')::boolean,false)) END,
      'order_visit_rate',CASE WHEN m.fuso_origem='America/Sao_Paulo' AND m.kind='visits' AND nullif(m.metrics->>'visits','') IS NOT NULL
          AND (m.metrics->>'visits')::numeric>0 AND ma.id IS NOT NULL THEN round(100.0*(SELECT count(DISTINCT i.pedido_id)
            FROM public.gestao_fatos_item i JOIN public.gestao_fatos_pedido o ON o.pedido_id=i.pedido_id
            WHERE i.anuncio_id=ma.id AND i.sold_on=m.periodo_inicio AND o.account_id=m.account_id
              AND coalesce((o.payload->>'eligible')::boolean,false))/(m.metrics->>'visits')::numeric,2) END,
      'partial',m.parcial,'semantica',m.semantica,'source',m.source)
      ORDER BY m.periodo_inicio,ma.id) AS rows,max(m.collected_at) AS updated_at
    FROM public.gestao_metricas_anuncio_periodo m
    LEFT JOIN public.marketplace_anuncios ma ON ma.integration_id=m.account_id AND ma.item_externo_id=m.resource_id
    WHERE m.periodo_inicio BETWEEN p_start AND p_end
      AND m.semantica='diaria' AND m.kind='visits' AND m.recurso_tipo='listing'
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
      SELECT * FROM grouped ORDER BY
       CASE WHEN p_direction='asc' THEN CASE p_sort WHEN 'sales' THEN sales WHEN 'orders' THEN orders WHEN 'units' THEN units END END ASC NULLS LAST,
       CASE WHEN p_direction='desc' THEN CASE p_sort WHEN 'sales' THEN sales WHEN 'orders' THEN orders WHEN 'units' THEN units END END DESC NULLS LAST,
       CASE WHEN p_sort='group_label' AND p_direction='asc' THEN group_label END ASC,
       CASE WHEN p_sort='group_label' AND p_direction='desc' THEN group_label END DESC,
       group_key,currency LIMIT greatest(1,least(p_limit,500)) OFFSET greatest(0,p_offset)
    ) page_row),'[]'::jsonb),
    'total_rows',(SELECT count(*) FROM grouped),
    'page',greatest(0,p_offset)/greatest(1,p_limit)+1,
    'per_page',greatest(1,least(p_limit,500)),
    'totals',(SELECT to_jsonb(totals) FROM totals),
    'series',coalesce((SELECT jsonb_agg(to_jsonb(series)) FROM series),'[]'::jsonb),
    'traffic',coalesce((SELECT rows FROM traffic),'[]'::jsonb),
    'coverage',(SELECT jsonb_build_object('item_groups',item_groups,'known_subtotals',known_subtotals,
      'subtotal_percent',round(100.0*known_subtotals/nullif(item_groups,0),2),
      'orders_materialized',(SELECT count(DISTINCT pedido_id) FROM selected),
      'orders_projected',(SELECT count(*) FROM public.gestao_fatos_pedido o WHERE o.sold_on BETWEEN p_start AND p_end
         AND (p_filters->>'account_id' IS NULL OR o.account_id=(p_filters->>'account_id')::integer)
         AND (p_filters->>'platform' IS NULL OR lower(o.marketplace)=lower(p_filters->>'platform'))),
      'linked_item_groups',(SELECT count(*) FROM selected WHERE produto_id IS NOT NULL),
      'traffic_available',(SELECT coalesce(jsonb_array_length(rows),0)>0 FROM traffic)) FROM totals),
    'updated_at',greatest((SELECT max(synced_at) FROM selected),
      (SELECT updated_at FROM traffic)),
    'group_by',p_group_by,
    'definitions',jsonb_build_object('sales','Subtotal conhecido das mercadorias em pedidos elegíveis.',
      'orders','Contagem distinta de pedidos elegíveis.','units','Quantidade conhecida em pedidos elegíveis.',
      'traffic','Métricas diárias por anúncio; não são distribuídas entre variações.')) INTO result;
  RETURN result;
END $$;

