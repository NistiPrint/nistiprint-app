-- All report selections, aggregation and drill-down pagination execute in PostgreSQL.
CREATE FUNCTION public.gestao_selected(p_start date,p_end date,p_filters jsonb DEFAULT '{}')
RETURNS TABLE(pedido_id integer,sold_on date,account_id integer,marketplace text,payload jsonb)
LANGUAGE sql STABLE AS $$
 WITH base AS NOT MATERIALIZED (
 SELECT f.* FROM public.gestao_fatos_pedido f
 WHERE f.sold_on BETWEEN p_start AND p_end
 AND (NOT p_filters ? 'account_id' OR f.account_id=(p_filters->>'account_id')::integer)
 AND (NOT p_filters ? 'marketplace' OR f.marketplace=p_filters->>'marketplace')
 AND (NOT p_filters ? 'logistics' OR f.payload->>'logistics'=p_filters->>'logistics')
 AND (NOT p_filters ? 'product_id' OR f.payload->'items' @> jsonb_build_array(jsonb_build_object('product_id',(p_filters->>'product_id')::integer)))
 AND (NOT p_filters ? 'category_id' OR f.payload->'items' @> jsonb_build_array(jsonb_build_object('category_id',(p_filters->>'category_id')::integer)))
 AND (NOT p_filters ? '_cutoff_date' OR f.sold_on<(p_filters->>'_cutoff_date')::date
 OR (f.payload->>'hour' IS NOT NULL AND ((f.payload->>'sold_at')::timestamptz AT TIME ZONE 'America/Sao_Paulo')::time<=(p_filters->>'_cutoff_time')::time))
 )
 SELECT f.pedido_id,f.sold_on,f.account_id,f.marketplace,f.payload FROM base f
 WHERE NOT (p_filters ? 'product_id' OR p_filters ? 'category_id')
 UNION ALL
 SELECT f.pedido_id,f.sold_on,f.account_id,f.marketplace,
 jsonb_set(jsonb_set(jsonb_set(f.payload,'{items}',items.value),'{finance}','null'),'{names}',
 (SELECT coalesce(jsonb_agg(n),'[]') FROM jsonb_array_elements(f.payload->'names') n
 WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(items.value) i WHERE i->>'id'=n->>'item_id')))
 FROM base f
 CROSS JOIN LATERAL (SELECT coalesce(jsonb_agg(i),'[]') value FROM jsonb_array_elements(f.payload->'items') i
 WHERE (NOT p_filters ? 'product_id' OR i->>'product_id'=p_filters->>'product_id')
 AND (NOT p_filters ? 'category_id' OR i->>'category_id'=p_filters->>'category_id')) items
 WHERE (p_filters ? 'product_id' OR p_filters ? 'category_id') AND jsonb_array_length(items.value)>0;
$$;

CREATE FUNCTION public.gestao_summary(p_start date,p_end date,p_filters jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 WITH orders AS (
 SELECT p.*, (payload->>'eligible')::boolean eligible,
   (SELECT CASE WHEN count(*)>0 AND count(*)=count(i->>'subtotal') THEN sum((i->>'subtotal')::numeric) END FROM jsonb_array_elements(payload->'items') i) sales,
   (SELECT sum((i->>'quantity')::numeric) FROM jsonb_array_elements(payload->'items') i) units
 FROM gestao_selected(p_start,p_end,p_filters) p
 ), counts AS (SELECT count(*) created,count(*) FILTER(WHERE eligible) orders,
 count(sales) FILTER(WHERE eligible) known,sum(sales) FILTER(WHERE eligible) sales,
 coalesce(sum(units) FILTER(WHERE eligible),0) units,avg(sales) FILTER(WHERE eligible) ticket,
 coalesce(sum((payload->>'total')::numeric) FILTER(WHERE eligible),0) buyer_total,
 count(*) FILTER(WHERE payload->>'stage'='cancelled') cancelled,
 count(*) FILTER(WHERE payload->>'stage'='returned') returned,
 count(*) FILTER(WHERE payload->>'stage'='refunded') refunded,
 count(*) FILTER(WHERE payload->>'stage'='awaiting_payment') awaiting_payment,
 count(*) FILTER(WHERE payload->>'stage'='unknown') unknown,
 count(*) FILTER(WHERE payload->>'stage'='partially_refunded' OR payload->>'payment_status' IN ('partially_refunded','partial_refund')) partially_refunded FROM orders)
 SELECT jsonb_build_object('created',created,'orders',orders,'sales',CASE WHEN orders=0 THEN 0 ELSE round(sales,2) END,
 'sales_known_orders',known,'sales_coverage',round(100.0*known/nullif(orders,0),2),'units',units,'ticket',round(ticket,2),
 'buyer_total',buyer_total,'cancelled',cancelled,'returned',returned,'refunded',refunded,'partially_refunded',partially_refunded,
 'awaiting_payment',awaiting_payment,'unknown',unknown,'cancel_rate',round(100.0*cancelled/nullif(created,0),2)) FROM counts;
$$;

CREATE TABLE public.gestao_daily (
 day date NOT NULL,account_id integer NOT NULL,marketplace text NOT NULL,stats jsonb NOT NULL,
 PRIMARY KEY(day,account_id,marketplace)
);
CREATE TABLE public.gestao_daily_dirty(day date PRIMARY KEY);
CREATE FUNCTION public.gestao_mark_daily() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN
 IF TG_OP<>'DELETE' THEN INSERT INTO gestao_daily_dirty VALUES(NEW.sold_on) ON CONFLICT DO NOTHING; END IF;
 IF TG_OP<>'INSERT' THEN INSERT INTO gestao_daily_dirty VALUES(OLD.sold_on) ON CONFLICT DO NOTHING; END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER gestao_daily_dirty AFTER INSERT OR UPDATE OR DELETE ON public.gestao_fatos_pedido
FOR EACH ROW EXECUTE FUNCTION public.gestao_mark_daily();
INSERT INTO public.gestao_daily_dirty SELECT DISTINCT sold_on FROM public.gestao_fatos_pedido ON CONFLICT DO NOTHING;
CREATE FUNCTION public.gestao_refresh_daily() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path=public,pg_temp AS $$
DECLARE d date; a record; n integer:=0;
BEGIN
 FOR d IN SELECT day FROM gestao_daily_dirty ORDER BY day LIMIT 10 FOR UPDATE SKIP LOCKED LOOP
 DELETE FROM gestao_daily WHERE day=d;
 FOR a IN SELECT DISTINCT account_id,marketplace FROM gestao_fatos_pedido WHERE sold_on=d AND account_id IS NOT NULL LOOP
 INSERT INTO gestao_daily VALUES(d,a.account_id,a.marketplace,gestao_summary(d,d,jsonb_build_object('account_id',a.account_id,'marketplace',a.marketplace)));
 END LOOP;
 DELETE FROM gestao_daily_dirty WHERE day=d; n:=n+1;
 END LOOP; RETURN n;
END $$;

CREATE FUNCTION public.gestao_report_data(p_start date,p_end date,p_filters jsonb DEFAULT '{}',p_finance boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb; current_summary jsonb; previous_summary jsonb; previous_start date:=p_start-(p_end-p_start+1); dimension text; buckets jsonb; ranks jsonb:='{}';
BEGIN
 current_summary:=gestao_summary(p_start,p_end,p_filters);
 previous_summary:=gestao_summary(previous_start,p_start-1,p_filters);
 result:=jsonb_build_object('summary',current_summary,'previous',previous_summary,
 'daily',(SELECT coalesce(jsonb_agg(jsonb_build_object('day',d::date)||gestao_summary(d::date,d::date,p_filters) ORDER BY d),'[]')
 FROM generate_series(p_start,p_end,interval '1 day') d),
 'changes',jsonb_build_object('sales',null,'orders',null,'units',null),
 'comparison_note',null,
 'projection_pending',(SELECT count(*) FROM gestao_outbox),
 'last_synced_at',(SELECT max(synced_at) FROM gestao_fatos_pedido),
 'collections',(SELECT coalesce(jsonb_agg(to_jsonb(c)-ARRAY['checkpoint','lease_until']),'[]') FROM gestao_coletas c
 WHERE (NOT p_filters ? 'account_id' OR c.account_id=(p_filters->>'account_id')::integer)
 AND (NOT p_filters ? 'marketplace' OR EXISTS(SELECT 1 FROM installed_integrations a WHERE a.id=c.account_id
 AND coalesce(to_jsonb(a)->>'platform_slug',to_jsonb(a)->>'module_id')=p_filters->>'marketplace'))));

 WITH selected AS MATERIALIZED(SELECT * FROM gestao_selected(p_start,p_end,p_filters)),
 eligible AS MATERIALIZED(SELECT * FROM selected WHERE (payload->>'eligible')::boolean),
 items AS MATERIALIZED(SELECT e.pedido_id,e.account_id,e.marketplace,e.payload->>'account_name' account_name,i.* FROM eligible e
 CROSS JOIN LATERAL jsonb_to_recordset(e.payload->'items') AS i(id integer,product_id integer,name text,mapping text,
 family_id integer,family_name text,category_id integer,format text,listing text,listing_title text,variation text,variation_name text,
 quantity numeric,subtotal numeric,unit_cost numeric,cost_estimated boolean)),
 products AS (SELECT coalesce('product:'||product_id::text,'listing:'||account_id||':'||coalesce(listing,id::text)||':'||coalesce(variation,'')) key,
 max(name) name,max(product_id) product_id,max(mapping) mapping,max(family_id) family_id,max(category_id) category_id,max(format) format,
 sum(subtotal) sales,sum(quantity) units,count(DISTINCT pedido_id) orders,
 round(sum(subtotal)/nullif(sum(quantity),0),2) unit_price FROM items GROUP BY 1),
 ranked AS (SELECT *,round(100.0*sales/nullif((current_summary->>'sales')::numeric,0),2) share,
 CASE WHEN coalesce(sum(sales) OVER(ORDER BY sales DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)<.8*(current_summary->>'sales')::numeric THEN 'A'
 WHEN coalesce(sum(sales) OVER(ORDER BY sales DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)<.95*(current_summary->>'sales')::numeric THEN 'B' ELSE 'C' END abc,
 null::numeric change,'{}'::jsonb channels FROM products ORDER BY sales DESC NULLS LAST LIMIT 100),
 names AS (SELECT kind,lower(n.value->>kind) key,min(n.value->>kind) name,count(*) occurrences,
 sum((n.value->>'quantity')::numeric) units,count(n.value->>'quantity') quantity_known,
 count(*) FILTER(WHERE (n.value->>'confirmed')::boolean) confirmed
 FROM eligible e CROSS JOIN LATERAL jsonb_array_elements(e.payload->'names') n(value)
 CROSS JOIN (VALUES('name'),('initial')) kinds(kind)
 WHERE n.value->>'status'='SUCCESS' AND nullif(n.value->>kind,'') IS NOT NULL GROUP BY kind,lower(n.value->>kind)
 ORDER BY occurrences DESC LIMIT 100),
 channels AS (SELECT marketplace,account_id,max(payload->>'account_name') name,
 gestao_summary(p_start,p_end,p_filters||jsonb_build_object('account_id',account_id,'marketplace',marketplace)) stats
 FROM selected GROUP BY marketplace,account_id),
 regions AS (SELECT coalesce(payload->>'region','Não informado') region,coalesce(payload->>'city','Não informada') city,
 count(*) orders,sum((SELECT sum((i->>'subtotal')::numeric) FROM jsonb_array_elements(payload->'items') i)) sales
 FROM eligible GROUP BY 1,2 ORDER BY sales DESC NULLS LAST LIMIT 100)
 SELECT result||jsonb_build_object('products',(SELECT coalesce(jsonb_agg(to_jsonb(r)),'[]') FROM ranked r),
 'names',(SELECT coalesce(jsonb_agg(to_jsonb(n)),'[]') FROM names n),
 'channels',(SELECT coalesce(jsonb_agg(jsonb_build_object('marketplace',c.marketplace,'account_id',c.account_id,'name',c.name)||c.stats),'[]') FROM channels c),
 'regions',(SELECT coalesce(jsonb_agg(to_jsonb(r)),'[]') FROM regions r),
 'quality',jsonb_build_object('orders',(SELECT count(*) FROM selected),'items',(SELECT count(*) FROM items),
 'mapped_items',(SELECT count(*) FROM items WHERE product_id IS NOT NULL),'mapping_conflicts',(SELECT count(*) FROM items WHERE mapping='conflict'),
 'geography',(SELECT round(100.0*count(payload->>'region')/nullif(count(*),0),2) FROM eligible),
 'buyer_identity',(SELECT round(100.0*count(payload->>'buyer_key')/nullif(count(*),0),2) FROM eligible),
 'hour',(SELECT round(100.0*count(payload->>'hour')/nullif(count(*),0),2) FROM eligible)),
 'personalization',jsonb_build_object('eligible_orders',(SELECT count(*) FROM eligible WHERE (payload->>'personalized')::boolean),
 'identified_orders',(SELECT count(*) FROM eligible e WHERE (e.payload->>'personalized')::boolean AND EXISTS(SELECT 1 FROM jsonb_array_elements(e.payload->'names') n WHERE n->>'status'='SUCCESS' AND (n->>'name' IS NOT NULL OR n->>'initial' IS NOT NULL))),
 'pending',(SELECT count(*) FROM eligible e CROSS JOIN LATERAL jsonb_array_elements(e.payload->'names') n WHERE n->>'status'='NEEDS_REVIEW')))
 INTO result;

 WITH buyers AS (SELECT DISTINCT payload->>'buyer_key' buyer FROM gestao_selected(p_start,p_end,p_filters)
 WHERE (payload->>'eligible')::boolean AND payload->>'buyer_key' IS NOT NULL),
 history AS (SELECT b.buyer,min(f.sold_on) first_day,count(*) purchases FROM buyers b JOIN gestao_fatos_pedido f
 ON f.payload->>'buyer_key'=b.buyer AND (f.payload->>'eligible')::boolean AND f.sold_on<=p_end GROUP BY b.buyer)
 SELECT result||jsonb_build_object('customers',jsonb_build_object('identified',count(*),'returning',count(*) FILTER(WHERE first_day<p_start),
 'new_observed',count(*) FILTER(WHERE first_day>=p_start),'repeat_rate',round(100.0*count(*) FILTER(WHERE first_day<p_start)/nullif(count(*),0),2),
 'avg_gap_days',null,'segments','[]'::jsonb,'cohorts','[]'::jsonb)) INTO result FROM history;

 SELECT result||jsonb_build_object('coverage',coalesce(jsonb_agg(to_jsonb(c)),'[]')) INTO result FROM
 (SELECT marketplace,account_id,min(sold_on) "from",max(sold_on) "to",count(*) orders FROM gestao_fatos_pedido
 WHERE sold_on<=p_end AND (NOT p_filters ? 'account_id' OR account_id=(p_filters->>'account_id')::integer)
 AND (NOT p_filters ? 'marketplace' OR marketplace=p_filters->>'marketplace') GROUP BY marketplace,account_id) c;

 FOR dimension IN SELECT unnest(ARRAY['listings','families','categories','formats']) LOOP
 WITH items AS(SELECT f.pedido_id,f.account_id,i FROM gestao_selected(p_start,p_end,p_filters) f
 CROSS JOIN LATERAL jsonb_array_elements(f.payload->'items') i WHERE (f.payload->>'eligible')::boolean),
 groups AS(SELECT CASE dimension WHEN 'listings' THEN account_id||':'||coalesce(i->>'listing',i->>'id')||':'||coalesce(i->>'variation','')
 WHEN 'families' THEN coalesce(i->>'family_id','unknown') WHEN 'categories' THEN coalesce(i->>'category_id','unknown') ELSE coalesce(i->>'format','unknown') END key,
 max(CASE dimension WHEN 'listings' THEN coalesce(i->>'listing_title',i->>'name') WHEN 'families' THEN coalesce(i->>'family_name','Não informada')
 WHEN 'categories' THEN coalesce(i->>'category_id','Não informada') ELSE coalesce(i->>'format','Não informado') END) name,
 sum((i->>'subtotal')::numeric) sales,sum((i->>'quantity')::numeric) units,count(DISTINCT pedido_id) orders FROM items GROUP BY 1 ORDER BY sales DESC NULLS LAST LIMIT 100)
 SELECT coalesce(jsonb_agg(to_jsonb(g)),'[]') INTO buckets FROM groups g;
 ranks:=ranks||jsonb_build_object(dimension,buckets);
 END LOOP;
 result:=result||jsonb_build_object('rankings',ranks);
 IF p_finance THEN
 WITH selected AS(SELECT * FROM gestao_selected(p_start,p_end,p_filters) WHERE (payload->>'eligible')::boolean OR jsonb_typeof(payload->'finance')='object'),
 costs AS(SELECT f.*,payload->'finance' finance,CASE WHEN (payload->'finance'->'components') ?& ARRAY['net_payout','taxes','operating_cost'] THEN (SELECT CASE WHEN count(*)>0 AND count(i->>'unit_cost')=count(*) AND count(i->>'quantity')=count(*)
 THEN sum((i->>'unit_cost')::numeric*(i->>'quantity')::numeric) END FROM jsonb_array_elements(payload->'items') i) END item_cost FROM selected f),
 margins AS(SELECT pedido_id,payload->>'number' number,payload->>'account_name' account,finance->>'source' source,finance->'components' components,
 CASE WHEN (payload->>'eligible')::boolean THEN item_cost ELSE (finance->'components'->>'cogs')::numeric END cost,finance,payload FROM costs),
 results AS(SELECT *, (components->>'net_payout')::numeric-cost-(components->>'taxes')::numeric-(components->>'operating_cost')::numeric before_ads FROM margins),
 finals AS(SELECT *,before_ads-(components->>'ads')::numeric after_ads,CASE WHEN before_ads IS NULL THEN 'incomplete'
 WHEN NOT coalesce((finance->>'settled')::boolean,false) OR EXISTS(SELECT 1 FROM jsonb_array_elements(payload->'items') i WHERE (i->>'cost_estimated')::boolean) THEN 'estimated' ELSE 'settled' END state FROM results)
 SELECT result||jsonb_build_object('profitability',jsonb_build_object('orders',
 (SELECT coalesce(jsonb_agg(jsonb_build_object('id',pedido_id,'number',number,'account',account,'source',source,'components',components,'cost',coalesce(cost,CASE WHEN (payload->>'eligible')::boolean THEN (SELECT CASE WHEN count(*)>0 AND count(*)=count(i->>'unit_cost') AND count(*)=count(i->>'quantity') THEN sum((i->>'unit_cost')::numeric*(i->>'quantity')::numeric) END FROM jsonb_array_elements(payload->'items') i) END),'before_ads',before_ads,'after_ads',after_ads,'state',state)),'[]') FROM (SELECT * FROM finals ORDER BY pedido_id DESC LIMIT 100) x),
 'coverage',round(100.0*count(before_ads)/nullif(count(*),0),2),'before_ads',sum(before_ads),'after_ads',sum(after_ads),
 'after_ads_orders',count(after_ads),'estimated_orders',count(*) FILTER(WHERE state='estimated'),'channels','[]'::jsonb,'products','[]'::jsonb)) INTO result FROM finals;
 END IF;
 result:=result||gestao_report_extra(p_start,p_end,p_filters,p_finance,result);
 RETURN result;
END $$;

CREATE FUNCTION public.gestao_order_page(p_start date,p_end date,p_filters jsonb DEFAULT '{}',p_page integer DEFAULT 1)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 WITH selected AS MATERIALIZED(SELECT * FROM gestao_selected(p_start,p_end,p_filters)), page AS(
 SELECT jsonb_build_object('id',pedido_id,'number',payload->>'number','sold_on',sold_on,'marketplace',marketplace,
 'account',payload->>'account_name','stage',payload->>'stage','eligible',(payload->>'eligible')::boolean,
 'items_value',(SELECT CASE WHEN count(*)=count(i->>'subtotal') THEN sum((i->>'subtotal')::numeric) END FROM jsonb_array_elements(payload->'items') i),
 'items',(SELECT coalesce(jsonb_agg(i-ARRAY['unit_cost','cost_estimated','cost_source']),'[]') FROM jsonb_array_elements(payload->'items') i)) value
 FROM selected ORDER BY sold_on DESC,pedido_id DESC LIMIT 50 OFFSET (greatest(1,p_page)-1)*50)
 SELECT jsonb_build_object('data',(SELECT coalesce(jsonb_agg(value),'[]') FROM page),'total',(SELECT count(*) FROM selected));
$$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gestao_daily','gestao_daily_dirty'] LOOP
 EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('REVOKE ALL ON public.%I FROM anon,authenticated',t);
 EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.gestao_selected(date,date,jsonb),public.gestao_summary(date,date,jsonb),public.gestao_refresh_daily(),
public.gestao_report_data(date,date,jsonb,boolean),public.gestao_order_page(date,date,jsonb,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_selected(date,date,jsonb),public.gestao_summary(date,date,jsonb),public.gestao_refresh_daily(),
public.gestao_report_data(date,date,jsonb,boolean),public.gestao_order_page(date,date,jsonb,integer) TO service_role;

CREATE TABLE public.gestao_report_revisions(account_id integer PRIMARY KEY,revision bigint NOT NULL);
INSERT INTO public.gestao_report_revisions VALUES(0,1);
CREATE FUNCTION public.gestao_invalidate_report() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE aid integer; r jsonb;
BEGIN
 INSERT INTO gestao_report_revisions VALUES(0,nextval('gestao_generation_seq'))
 ON CONFLICT(account_id) DO UPDATE SET revision=excluded.revision;
 IF TG_OP<>'DELETE' THEN r:=to_jsonb(NEW); ELSE r:=to_jsonb(OLD); END IF;
 aid:=(r->>'account_id')::integer;
 IF aid IS NOT NULL AND aid<>0 THEN
 INSERT INTO gestao_report_revisions VALUES(aid,nextval('gestao_generation_seq'))
 ON CONFLICT(account_id) DO UPDATE SET revision=excluded.revision;
 END IF;
 RETURN NULL;
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gestao_fatos_pedido','gestao_metas','gestao_metricas_anuncio','gestao_coletas'] LOOP
 EXECUTE format('CREATE TRIGGER gestao_invalidate_report AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.gestao_invalidate_report()',t);
 END LOOP;
END $$;
CREATE FUNCTION public.gestao_report_revision(p_account integer DEFAULT 0) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT coalesce((SELECT revision FROM gestao_report_revisions WHERE account_id=p_account),0);
$$;

CREATE FUNCTION public.gestao_report_extra(p_start date,p_end date,p_filters jsonb,p_finance boolean,p_report jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE result jsonb:='{}'; previous_start date:=p_start-(p_end-p_start+1); anchor date:=least(p_end,(now() AT TIME ZONE 'America/Sao_Paulo')::date-1);
 current_comp jsonb; previous_comp jsonb; clock_time time:=(now() AT TIME ZONE 'America/Sao_Paulo')::time;
BEGIN
 WITH selected AS MATERIALIZED(SELECT * FROM gestao_selected(p_start,p_end,p_filters)),
 valid AS MATERIALIZED(SELECT * FROM selected WHERE (payload->>'eligible')::boolean),
 events AS(SELECT e.* FROM gestao_apontamentos e JOIN gestao_selected('0001-01-01',p_end,p_filters) f ON f.pedido_id=e.pedido_id
 WHERE e.occurred_at>=(p_start::timestamp AT TIME ZONE 'America/Sao_Paulo')
 AND e.occurred_at<((p_end+1)::timestamp AT TIME ZONE 'America/Sao_Paulo')),
 dispatches AS(SELECT f.payload FROM gestao_fatos_pedido f JOIN gestao_selected('0001-01-01',p_end,p_filters) s USING(pedido_id)
 WHERE gestao_dispatch_day(f.payload) BETWEEN p_start AND p_end AND f.payload->>'deadline' IS NOT NULL),
 hours AS(SELECT h "hour",count(*) FILTER(WHERE v.pedido_id IS NOT NULL) orders,
 sum((SELECT sum((i->>'subtotal')::numeric) FROM jsonb_array_elements(v.payload->'items') i)) sales
 FROM generate_series(0,23) h LEFT JOIN valid v ON (v.payload->>'hour')::integer=h GROUP BY h ORDER BY h),
 pair_items AS(SELECT DISTINCT pedido_id,coalesce('product:'||(i->>'product_id'),'listing:'||account_id||':'||coalesce(i->>'listing',i->>'id')||':'||coalesce(i->>'variation','')) key,
 i->>'name' name FROM valid CROSS JOIN LATERAL jsonb_array_elements(payload->'items') i),
 pairs AS(SELECT a.key "first",b.key "second",max(a.name) first_name,max(b.name) second_name,count(*) orders
 FROM pair_items a JOIN pair_items b ON a.pedido_id=b.pedido_id AND a.key<b.key GROUP BY a.key,b.key ORDER BY orders DESC LIMIT 50)
 SELECT jsonb_build_object('hours',(SELECT coalesce(jsonb_agg(to_jsonb(h)),'[]') FROM hours h),
 'pairs',(SELECT coalesce(jsonb_agg(to_jsonb(p)),'[]') FROM pairs p),
 'operations',jsonb_build_object('events',(SELECT count(*) FROM events),'duration_minutes',(SELECT sum(duration_minutes) FROM events),
 'late_dispatches',(SELECT count(*) FROM dispatches WHERE nullif(payload->>'shipped_at','')::timestamptz>nullif(payload->>'deadline','')::timestamptz),
 'observed_dispatches',(SELECT count(*) FROM dispatches))) INTO result;

 WITH buyers AS(SELECT DISTINCT payload->>'buyer_key' buyer FROM gestao_selected(p_start,p_end,p_filters)
 WHERE (payload->>'eligible')::boolean AND payload->>'buyer_key' IS NOT NULL),
 history AS(SELECT b.buyer,f.sold_on,lag(f.sold_on) OVER(PARTITION BY b.buyer ORDER BY f.sold_on,f.pedido_id) previous,
 min(f.sold_on) OVER(PARTITION BY b.buyer) first_day,count(*) OVER(PARTITION BY b.buyer) purchases
 FROM buyers b JOIN gestao_fatos_pedido f ON f.payload->>'buyer_key'=b.buyer
 AND (f.payload->>'eligible')::boolean AND f.sold_on<=p_end),
 segments AS(SELECT CASE WHEN purchases=1 THEN 'Uma compra' WHEN purchases<=3 THEN 'Duas ou três compras' ELSE 'Quatro ou mais compras' END name,
 count(DISTINCT buyer) buyers FROM history GROUP BY 1),
 cohorts AS(SELECT to_char(first_day,'YYYY-MM') cohort,to_char(sold_on,'YYYY-MM') "month",count(DISTINCT buyer) buyers
 FROM history WHERE sold_on>=p_start GROUP BY 1,2),
 total AS(SELECT count(*) identified,count(*) FILTER(WHERE first_day<p_start) "returning",
 count(*) FILTER(WHERE first_day>=p_start) new_observed FROM (SELECT DISTINCT buyer,first_day FROM history) h)
 SELECT result||jsonb_build_object('customers',jsonb_build_object('identified',t.identified,'returning',t.returning,'new_observed',t.new_observed,
 'repeat_rate',round(100.0*t.returning/nullif(t.identified,0),2),'avg_gap_days',(SELECT round(avg(sold_on-previous),2) FROM history WHERE sold_on>=p_start),
 'segments',(SELECT coalesce(jsonb_agg(to_jsonb(s)),'[]') FROM segments s),'cohorts',(SELECT coalesce(jsonb_agg(to_jsonb(c)),'[]') FROM cohorts c))) INTO result FROM total t;

 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'coverage') c WHERE (c->>'from')::date>anchor-34)
 AND jsonb_array_length(p_report->'coverage')>0 THEN
 SELECT result||jsonb_build_object('forecast_history',jsonb_agg(jsonb_build_object('day',d::date)||gestao_summary(d::date,d::date,p_filters) ORDER BY d))
 INTO result FROM generate_series(anchor-34,anchor,interval '1 day') d;
 END IF;

 -- Product-channel comparison and growth preserve the listing/product identity levels.
 WITH current_items AS(SELECT f.*,i FROM gestao_selected(p_start,p_end,p_filters) f
 CROSS JOIN LATERAL jsonb_array_elements(payload->'items') i WHERE (payload->>'eligible')::boolean),
 previous_items AS(SELECT f.*,i FROM gestao_selected(previous_start,p_start-1,p_filters) f
 CROSS JOIN LATERAL jsonb_array_elements(payload->'items') i WHERE (payload->>'eligible')::boolean),
 grouped AS(SELECT coalesce('product:'||(i->>'product_id'),'listing:'||account_id||':'||coalesce(i->>'listing',i->>'id')||':'||coalesce(i->>'variation','')) key,
 marketplace||' / '||(payload->>'account_name') channel,sum((i->>'subtotal')::numeric) sales,sum((i->>'quantity')::numeric) units FROM current_items GROUP BY 1,2),
 old AS(SELECT coalesce('product:'||(i->>'product_id'),'listing:'||account_id||':'||coalesce(i->>'listing',i->>'id')||':'||coalesce(i->>'variation','')) key,
 sum((i->>'subtotal')::numeric) sales FROM previous_items GROUP BY 1),
 products AS(SELECT p||jsonb_build_object('change',round(100.0*((p->>'sales')::numeric/nullif(o.sales,0)-1),2),
 'channels',(SELECT coalesce(jsonb_object_agg(g.channel,jsonb_build_object('sales',g.sales,'units',g.units)),'{}') FROM grouped g WHERE g.key=p->>'key')) value
 FROM jsonb_array_elements(p_report->'products') p LEFT JOIN old o ON o.key=p->>'key')
 SELECT result||jsonb_build_object('products',(SELECT coalesce(jsonb_agg(value),'[]') FROM products)) INTO result;

 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'coverage') c WHERE (c->>'from')::date>previous_start) THEN
 result:=result||jsonb_build_object('changes',jsonb_build_object(
 'sales',round(100.0*((p_report->'summary'->>'sales')::numeric/nullif((p_report->'previous'->>'sales')::numeric,0)-1),2),
 'orders',round(100.0*((p_report->'summary'->>'orders')::numeric/nullif((p_report->'previous'->>'orders')::numeric,0)-1),2),
 'units',round(100.0*((p_report->'summary'->>'units')::numeric/nullif((p_report->'previous'->>'units')::numeric,0)-1),2)));
 ELSE result:=result||jsonb_build_object('comparison_note','Cobertura histórica insuficiente em pelo menos uma conta para comparar os períodos completos.'); END IF;
 IF p_end=(now() AT TIME ZONE 'America/Sao_Paulo')::date THEN
 current_comp:=gestao_summary(p_start,p_end,p_filters||jsonb_build_object('_cutoff_date',p_end,'_cutoff_time',clock_time));
 previous_comp:=gestao_summary(previous_start,p_start-1,p_filters||jsonb_build_object('_cutoff_date',p_start-1,'_cutoff_time',clock_time));
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'coverage') c WHERE (c->>'from')::date>previous_start) THEN
 result:=result||jsonb_build_object('changes',jsonb_build_object(
 'sales',round(100.0*((current_comp->>'sales')::numeric/nullif((previous_comp->>'sales')::numeric,0)-1),2),
 'orders',round(100.0*((current_comp->>'orders')::numeric/nullif((previous_comp->>'orders')::numeric,0)-1),2),
 'units',round(100.0*((current_comp->>'units')::numeric/nullif((previous_comp->>'units')::numeric,0)-1),2)),
 'comparison_note','Último dia comparado até o horário atual; registros sem horário entram apenas em dias completos.');
 END IF;
 END IF;
 IF p_finance THEN
 SELECT result||jsonb_build_object('ad_metrics',coalesce(jsonb_agg(to_jsonb(m)),'[]')) INTO result
 FROM (SELECT m.* FROM gestao_metricas_anuncio m WHERE day BETWEEN p_start AND p_end
 AND (NOT p_filters ? 'account_id' OR account_id=(p_filters->>'account_id')::integer)
 AND (NOT p_filters ? 'marketplace' OR EXISTS(SELECT 1 FROM installed_integrations a WHERE a.id=m.account_id
 AND coalesce(to_jsonb(a)->>'platform_slug',to_jsonb(a)->>'module_id')=p_filters->>'marketplace'))
 ORDER BY day DESC,account_id,resource_id LIMIT 500) m;
 WITH margins AS MATERIALIZED(SELECT * FROM gestao_margin_rows(p_start,p_end,p_filters)),
 channels AS(SELECT marketplace,max(payload->>'account_name') name,account_id,count(*) orders,count(before_ads) known,
 round(100.0*count(before_ads)/nullif(count(*),0),2) coverage,sum(before_ads) before_ads,sum(after_ads) after_ads
 FROM margins GROUP BY marketplace,account_id ORDER BY before_ads DESC NULLS LAST),
 allocations AS(SELECT coalesce('product:'||(i->>'product_id'),'listing:'||account_id||':'||coalesce(i->>'listing',i->>'sku',i->>'id')||':'||coalesce(i->>'variation','')) key,
 i->>'name' name,net*(i->>'subtotal')::numeric/nullif(item_sales,0)-(i->>'unit_cost')::numeric*(i->>'quantity')::numeric before_ads,
 (components->>'ads')::numeric*(i->>'subtotal')::numeric/nullif(item_sales,0) ads FROM margins
 CROSS JOIN LATERAL jsonb_array_elements(payload->'items') i WHERE before_ads IS NOT NULL AND item_sales>0 AND (payload->>'eligible')::boolean),
 products AS(SELECT key,max(name) name,count(*) known,sum(before_ads) before_ads,sum(before_ads-ads) after_ads,
 'proporcional_ao_valor_dos_itens' allocation FROM allocations GROUP BY key ORDER BY before_ads DESC LIMIT 100)
 SELECT result||jsonb_build_object('profitability',(p_report->'profitability')||jsonb_build_object(
 'channels',(SELECT coalesce(jsonb_agg(to_jsonb(c)),'[]') FROM channels c),
 'products',(SELECT coalesce(jsonb_agg(to_jsonb(p)),'[]') FROM products p))) INTO result;
 END IF;
 RETURN result;
END $$;
ALTER TABLE public.gestao_report_revisions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.gestao_report_revisions FROM anon,authenticated;
GRANT ALL ON public.gestao_report_revisions TO service_role;
REVOKE ALL ON FUNCTION public.gestao_report_revision(integer),public.gestao_report_extra(date,date,jsonb,boolean,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_report_revision(integer),public.gestao_report_extra(date,date,jsonb,boolean,jsonb) TO service_role;

ALTER FUNCTION public.gestao_summary(date,date,jsonb) RENAME TO gestao_summary_raw;
CREATE FUNCTION public.gestao_summary(p_start date,p_end date,p_filters jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=public,pg_temp AS $$
DECLARE result jsonb; key text; value numeric;
BEGIN
 IF p_filters ?| ARRAY['product_id','category_id','logistics','_cutoff_date']
 OR EXISTS(SELECT 1 FROM gestao_daily_dirty WHERE day BETWEEN p_start AND p_end)
 OR EXISTS(SELECT 1 FROM gestao_fatos_pedido WHERE sold_on BETWEEN p_start AND p_end AND account_id IS NULL) THEN
 RETURN gestao_summary_raw(p_start,p_end,p_filters);
 END IF;
 result:='{}';
 FOR key IN SELECT unnest(ARRAY['created','orders','sales','sales_known_orders','units','buyer_total','cancelled','returned','refunded','partially_refunded','awaiting_payment','unknown']) LOOP
 SELECT sum((stats->>key)::numeric) INTO value FROM gestao_daily WHERE day BETWEEN p_start AND p_end
 AND (NOT p_filters ? 'account_id' OR account_id=(p_filters->>'account_id')::integer)
 AND (NOT p_filters ? 'marketplace' OR marketplace=p_filters->>'marketplace');
 result:=result||jsonb_build_object(key,coalesce(value,0));
 END LOOP;
 IF (result->>'orders')::numeric>0 AND (result->>'sales_known_orders')::numeric=0 THEN result:=jsonb_set(result,'{sales}','null'); END IF;
 RETURN result||jsonb_build_object('sales_coverage',round(100.0*(result->>'sales_known_orders')::numeric/nullif((result->>'orders')::numeric,0),2),
 'ticket',round((result->>'sales')::numeric/nullif((result->>'sales_known_orders')::numeric,0),2),
 'cancel_rate',round(100.0*(result->>'cancelled')::numeric/nullif((result->>'created')::numeric,0),2));
END $$;
-- Refresh must always read raw facts, even when the dirty row is locked locally.
CREATE OR REPLACE FUNCTION public.gestao_refresh_daily() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path=public,pg_temp AS $$
DECLARE d date; a record; n integer:=0;
BEGIN
 FOR d IN SELECT day FROM gestao_daily_dirty ORDER BY day LIMIT 10 FOR UPDATE SKIP LOCKED LOOP
 DELETE FROM gestao_daily WHERE day=d;
 FOR a IN SELECT DISTINCT account_id,marketplace FROM gestao_fatos_pedido WHERE sold_on=d AND account_id IS NOT NULL LOOP
 INSERT INTO gestao_daily VALUES(d,a.account_id,a.marketplace,gestao_summary_raw(d,d,jsonb_build_object('account_id',a.account_id,'marketplace',a.marketplace)));
 END LOOP;
 DELETE FROM gestao_daily_dirty WHERE day=d; n:=n+1;
 END LOOP; RETURN n;
END $$;
CREATE FUNCTION public.gestao_product_demand(p_start date,p_end date,p_filters jsonb,p_products integer[]) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT coalesce(jsonb_object_agg(product_id,units),'{}') FROM
 (SELECT (i->>'product_id')::integer product_id,sum((i->>'quantity')::numeric) units FROM gestao_selected(p_start,p_end,p_filters) f
 CROSS JOIN LATERAL jsonb_array_elements(payload->'items') i WHERE (payload->>'eligible')::boolean
 AND (i->>'product_id')::integer=ANY(p_products) GROUP BY 1) q;
$$;
REVOKE ALL ON FUNCTION public.gestao_summary(date,date,jsonb),public.gestao_product_demand(date,date,jsonb,integer[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_summary(date,date,jsonb),public.gestao_product_demand(date,date,jsonb,integer[]) TO service_role;

CREATE TABLE public.gestao_report_cache (
 cache_key text PRIMARY KEY,revision bigint NOT NULL,expires_at timestamptz NOT NULL,payload jsonb NOT NULL
);
CREATE FUNCTION public.gestao_report_cached(p_start date,p_end date,p_filters jsonb DEFAULT '{}',p_finance boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE key text:=md5(jsonb_build_array(p_start,p_end,p_filters,p_finance)::text); rev bigint; result jsonb;
BEGIN
 rev:=gestao_report_revision(coalesce((p_filters->>'account_id')::integer,0));
 SELECT payload INTO result FROM gestao_report_cache WHERE cache_key=key AND revision=rev AND expires_at>now();
 IF FOUND THEN RETURN result; END IF;
 result:=gestao_report_data(p_start,p_end,p_filters,p_finance);
 DELETE FROM gestao_report_cache WHERE expires_at<now();
 IF (SELECT count(*) FROM gestao_report_cache)>=256 THEN
 DELETE FROM gestao_report_cache WHERE cache_key IN(SELECT cache_key FROM gestao_report_cache ORDER BY expires_at LIMIT 32);
 END IF;
 INSERT INTO gestao_report_cache VALUES(key,rev,now()+interval '60 seconds',result)
 ON CONFLICT(cache_key) DO UPDATE SET revision=excluded.revision,expires_at=excluded.expires_at,payload=excluded.payload;
 RETURN result;
END $$;
ALTER TABLE public.gestao_report_cache ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.gestao_report_cache FROM anon,authenticated;
GRANT ALL ON public.gestao_report_cache TO service_role;
REVOKE ALL ON FUNCTION public.gestao_report_cached(date,date,jsonb,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_report_cached(date,date,jsonb,boolean) TO service_role;

CREATE FUNCTION public.gestao_margin_rows(p_start date,p_end date,p_filters jsonb)
RETURNS TABLE(pedido_id integer,account_id integer,marketplace text,payload jsonb,components jsonb,
 item_sales numeric,net numeric,cost numeric,before_ads numeric,after_ads numeric)
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 WITH orders AS(SELECT f.*,
 payload->'finance'->'components' components,
 CASE WHEN (payload->'finance'->'components') ?& ARRAY['net_payout','taxes','operating_cost'] THEN (SELECT CASE WHEN count(*)>0 AND count(*)=count(i->>'subtotal') THEN sum((i->>'subtotal')::numeric) END FROM jsonb_array_elements(payload->'items') i) END item_sales,
 CASE WHEN (payload->>'eligible')::boolean AND (payload->'finance'->'components') ?& ARRAY['net_payout','taxes','operating_cost'] THEN
 (SELECT CASE WHEN count(*)>0 AND count(*)=count(i->>'unit_cost') AND count(*)=count(i->>'quantity')
 THEN sum((i->>'unit_cost')::numeric*(i->>'quantity')::numeric) END FROM jsonb_array_elements(payload->'items') i)
 ELSE (payload->'finance'->'components'->>'cogs')::numeric END cost
 FROM gestao_selected(p_start,p_end,p_filters) f
 WHERE (payload->>'eligible')::boolean OR jsonb_typeof(payload->'finance')='object'),
 nets AS(SELECT *, (components->>'net_payout')::numeric-(components->>'taxes')::numeric-(components->>'operating_cost')::numeric net FROM orders)
 SELECT pedido_id,account_id,marketplace,payload,components,item_sales,net,cost,net-cost,net-cost-(components->>'ads')::numeric FROM nets;
$$;
REVOKE ALL ON FUNCTION public.gestao_margin_rows(date,date,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_margin_rows(date,date,jsonb) TO service_role;

CREATE FUNCTION public.gestao_export_page(p_start date,p_end date,p_filters jsonb DEFAULT '{}',p_after integer DEFAULT 0)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT coalesce(jsonb_agg(value ORDER BY pedido_id),'[]') FROM (
 SELECT pedido_id,jsonb_build_object('id',pedido_id,'number',payload->>'number','sold_on',sold_on,'marketplace',marketplace,
 'account',payload->>'account_name','stage',payload->>'stage','eligible',(payload->>'eligible')::boolean,
 'items_value',(SELECT CASE WHEN count(*)=count(i->>'subtotal') THEN sum((i->>'subtotal')::numeric) END FROM jsonb_array_elements(payload->'items') i)) value
 FROM gestao_selected(p_start,p_end,p_filters) WHERE pedido_id>p_after ORDER BY pedido_id LIMIT 500) q;
$$;
REVOKE ALL ON FUNCTION public.gestao_export_page(date,date,jsonb,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_export_page(date,date,jsonb,integer) TO service_role;

-- Projection emits ISO timestamps with explicit offsets. Naive legacy timestamps
-- are interpreted in the application's fixed time zone, never the session zone.
CREATE FUNCTION public.gestao_dispatch_day(p_payload jsonb) RETURNS date
LANGUAGE sql IMMUTABLE SET search_path=public,pg_temp AS $$
 SELECT CASE WHEN nullif(p_payload->>'shipped_at','') IS NULL THEN NULL
 WHEN p_payload->>'shipped_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
 THEN ((p_payload->>'shipped_at')::timestamptz AT TIME ZONE 'America/Sao_Paulo')::date
 ELSE (p_payload->>'shipped_at')::timestamp::date END;
$$;
CREATE INDEX gestao_fatos_dispatch ON public.gestao_fatos_pedido(public.gestao_dispatch_day(payload),account_id);
CREATE INDEX gestao_event_period ON public.gestao_apontamentos(occurred_at,pedido_id);
REVOKE ALL ON FUNCTION public.gestao_dispatch_day(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_dispatch_day(jsonb) TO service_role;
