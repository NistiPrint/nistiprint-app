-- Aggregates used by the Gestión dashboard. These are derived only from
-- already collected facts and remain behind the existing service_role RPC.
CREATE OR REPLACE FUNCTION public.gestao_metric_number(p_metrics jsonb,p_keys text[])
RETURNS numeric LANGUAGE sql IMMUTABLE SET search_path=public,pg_temp AS $$
  SELECT v.value::numeric
  FROM unnest(p_keys) WITH ORDINALITY AS k(key,position)
  CROSS JOIN LATERAL (SELECT p_metrics->>k.key AS value) v
  WHERE v.value ~ '^[+-]?[0-9]+([.][0-9]+)?$'
  ORDER BY position LIMIT 1;
$$;

CREATE FUNCTION public.gestao_report_visual_aggregates(
  p_start date,p_end date,p_filters jsonb,p_finance boolean)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH eligible AS MATERIALIZED (
    SELECT f.pedido_id,f.account_id,f.payload,
      CASE WHEN jsonb_array_length(f.payload->'items')>0
        AND (SELECT count(*)=count(i->>'subtotal')
             FROM jsonb_array_elements(f.payload->'items') i)
        THEN (SELECT sum((i->>'subtotal')::numeric)
              FROM jsonb_array_elements(f.payload->'items') i)
      END AS item_value
    FROM gestao_selected(p_start,p_end,p_filters) f
    WHERE (f.payload->>'eligible')::boolean
  ), states AS (
    SELECT coalesce(gestao_known_place(payload->>'region'),'Não informado') AS region,
      count(*) AS orders,count(item_value) AS known_value_orders,
      sum(item_value) AS items_value
    FROM eligible GROUP BY 1
  ), ad_source AS (
    SELECT m.account_id,m.day,m.kind,
      coalesce(to_jsonb(a)->>'platform_slug',to_jsonb(a)->>'module_id',m.source) AS platform,
      CASE WHEN m.kind='ads' THEN gestao_metric_number(m.metrics,ARRAY['cost','COST','expense']) END AS spend,
      CASE WHEN m.kind='ads' THEN gestao_metric_number(m.metrics,ARRAY['clicks','CLICKS']) END AS clicks,
      CASE WHEN m.kind='visits' THEN gestao_metric_number(m.metrics,ARRAY['visits','total_visits']) END AS visits
    FROM gestao_metricas_anuncio m
    LEFT JOIN installed_integrations a ON a.id=m.account_id
    WHERE p_finance AND m.day BETWEEN p_start AND p_end
      AND (NOT p_filters ? 'account_id' OR m.account_id=(p_filters->>'account_id')::integer)
      AND (NOT p_filters ? 'marketplace' OR
        coalesce(to_jsonb(a)->>'platform_slug',to_jsonb(a)->>'module_id',m.source)=p_filters->>'marketplace')
      AND m.kind IN ('ads','visits')
  ), ads AS (
    SELECT account_id,platform,day,kind,count(*) AS metric_rows,
      sum(spend) AS spend,count(spend) AS spend_rows,
      sum(clicks) AS clicks,count(clicks) AS clicks_rows,
      sum(visits) AS visits,count(visits) AS visits_rows
    FROM ad_source GROUP BY account_id,platform,day,kind
  )
  SELECT jsonb_build_object(
    'regions_by_state',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'region',region,'orders',orders,'known_value_orders',known_value_orders,
      'items_value',round(items_value,2),
      'value_coverage',round(100.0*known_value_orders/nullif(orders,0),2),
      'ticket',round(items_value/nullif(known_value_orders,0),2)
    ) ORDER BY items_value DESC NULLS LAST,orders DESC),'[]'::jsonb) FROM states),
    'advertising_daily',CASE WHEN p_finance THEN
      (SELECT coalesce(jsonb_agg(jsonb_build_object(
        'account_id',account_id,'platform',platform,'day',day,'kind',kind,
        'metric_rows',metric_rows,'spend',round(spend,2),
        'spend_coverage',round(100.0*spend_rows/nullif(metric_rows,0),2),
        'clicks',clicks,'clicks_coverage',round(100.0*clicks_rows/nullif(metric_rows,0),2),
        'visits',visits,'visits_coverage',round(100.0*visits_rows/nullif(metric_rows,0),2)
      ) ORDER BY day,account_id,kind),'[]'::jsonb) FROM ads)
      ELSE '[]'::jsonb END
  );
$$;

-- Extend the existing revision-aware database cache with the visual aggregates.
CREATE OR REPLACE FUNCTION public.gestao_report_cached(
  p_start date,p_end date,p_filters jsonb DEFAULT '{}',p_finance boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE key text:=md5(jsonb_build_array(p_start,p_end,p_filters,p_finance)::text);
  rev bigint; result jsonb;
BEGIN
  rev:=gestao_report_revision(coalesce((p_filters->>'account_id')::integer,0));
  SELECT payload INTO result FROM gestao_report_cache
  WHERE cache_key=key AND revision=rev AND expires_at>now();
  IF FOUND THEN RETURN result; END IF;

  result:=gestao_report_data(p_start,p_end,p_filters,p_finance);
  result:=result||gestao_report_supplement(p_start,p_end,p_filters,p_finance,result);
  result:=result||gestao_report_visual_aggregates(p_start,p_end,p_filters,p_finance);
  DELETE FROM gestao_report_cache WHERE expires_at<now();
  IF (SELECT count(*) FROM gestao_report_cache)>=256 THEN
    DELETE FROM gestao_report_cache WHERE cache_key IN
      (SELECT cache_key FROM gestao_report_cache ORDER BY expires_at LIMIT 32);
  END IF;
  INSERT INTO gestao_report_cache VALUES(key,rev,now()+interval '60 seconds',result)
  ON CONFLICT(cache_key) DO UPDATE SET revision=excluded.revision,
    expires_at=excluded.expires_at,payload=excluded.payload;
  RETURN result;
END $$;

REVOKE ALL ON FUNCTION public.gestao_metric_number(jsonb,text[]),
  public.gestao_report_visual_aggregates(date,date,jsonb,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_metric_number(jsonb,text[]),
  public.gestao_report_visual_aggregates(date,date,jsonb,boolean) TO service_role;
REVOKE ALL ON FUNCTION public.gestao_report_cached(date,date,jsonb,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_report_cached(date,date,jsonb,boolean) TO service_role;
