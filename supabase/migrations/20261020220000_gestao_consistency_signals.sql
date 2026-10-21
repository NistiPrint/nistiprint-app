-- Correct presentation aggregates and provide bounded evidence for management signals.
CREATE OR REPLACE FUNCTION public.gestao_known_place(p_value text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE WHEN nullif(btrim(p_value),'') IS NULL
   OR btrim(p_value) ~ '^[*xX#•-]+$'
   OR lower(btrim(p_value)) IN ('null','none','não informado','nao informado')
 THEN NULL ELSE btrim(p_value) END;
$$;

CREATE FUNCTION public.gestao_report_supplement(
 p_start date,p_end date,p_filters jsonb,p_finance boolean,p_report jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb:='{}'; previous_start date:=p_start-(p_end-p_start+1);
 current_filters jsonb:=p_filters; previous_filters jsonb:=p_filters;
 cutoff_time time:=(now() AT TIME ZONE 'America/Sao_Paulo')::time;
BEGIN
 IF p_end=(now() AT TIME ZONE 'America/Sao_Paulo')::date THEN
   current_filters:=current_filters||jsonb_build_object('_cutoff_date',p_end,'_cutoff_time',cutoff_time);
   previous_filters:=previous_filters||jsonb_build_object('_cutoff_date',p_start-1,'_cutoff_time',cutoff_time);
 END IF;

 WITH eligible AS MATERIALIZED (
   SELECT f.*,CASE WHEN jsonb_array_length(f.payload->'items')>0 AND
     (SELECT count(*)=count(i->>'subtotal') FROM jsonb_array_elements(f.payload->'items') i)
     THEN (SELECT sum((i->>'subtotal')::numeric) FROM jsonb_array_elements(f.payload->'items') i) END item_sales
   FROM gestao_selected(p_start,p_end,p_filters) f WHERE (f.payload->>'eligible')::boolean
 ), locations AS (
   SELECT coalesce(gestao_known_place(payload->>'region'),'Não informado') region,
     coalesce(gestao_known_place(payload->>'city'),'Não informada') city,
     count(*) orders,count(item_sales) known_orders,sum(item_sales) sales
   FROM eligible GROUP BY 1,2 ORDER BY sales DESC NULLS LAST LIMIT 100
 )
 SELECT jsonb_build_object(
   'regions',(SELECT coalesce(jsonb_agg(jsonb_build_object('region',region,'city',city,'orders',orders,
     'known_orders',known_orders,'sales',round(sales,2),
     'ticket',round(sales/nullif(known_orders,0),2)) ORDER BY sales DESC NULLS LAST,orders DESC),'[]') FROM locations),
   'quality',(p_report->'quality')||jsonb_build_object(
     'geography',(SELECT round(100.0*count(*) FILTER(WHERE gestao_known_place(payload->>'region') IS NOT NULL)/nullif(count(*),0),2) FROM eligible),
     'masked_geography',(SELECT count(*) FROM eligible WHERE btrim(payload->>'region') ~ '^[*xX#•-]+$'),
     'eligible_orders',(SELECT count(*) FROM eligible))) INTO result;

 WITH current_items AS (
   SELECT f.pedido_id,f.account_id,i.value item FROM gestao_selected(p_start,p_end,current_filters) f
   CROSS JOIN LATERAL jsonb_array_elements(f.payload->'items') i
   WHERE (f.payload->>'eligible')::boolean
 ), previous_items AS (
   SELECT f.pedido_id,f.account_id,i.value item FROM gestao_selected(previous_start,p_start-1,previous_filters) f
   CROSS JOIN LATERAL jsonb_array_elements(f.payload->'items') i
   WHERE (f.payload->>'eligible')::boolean
 ), current_group AS (
   SELECT coalesce('product:'||(item->>'product_id'),'listing:'||account_id||':'||coalesce(item->>'listing',item->>'sku',item->>'id')||':'||coalesce(item->>'variation','')) key,
     max(item->>'name') name,max((item->>'product_id')::integer) product_id,
     min(account_id) account_id,count(DISTINCT pedido_id) orders,
     CASE WHEN count(*)=count(item->>'subtotal') THEN sum((item->>'subtotal')::numeric) END sales
   FROM current_items GROUP BY 1
 ), previous_group AS (
   SELECT coalesce('product:'||(item->>'product_id'),'listing:'||account_id||':'||coalesce(item->>'listing',item->>'sku',item->>'id')||':'||coalesce(item->>'variation','')) key,
     max(item->>'name') name,max((item->>'product_id')::integer) product_id,
     min(account_id) account_id,count(DISTINCT pedido_id) orders,
     CASE WHEN count(*)=count(item->>'subtotal') THEN sum((item->>'subtotal')::numeric) END sales
   FROM previous_items GROUP BY 1
 ), movements AS (
   SELECT coalesce(c.key,p.key) key,coalesce(c.name,p.name) name,
     coalesce(c.product_id,p.product_id) product_id,coalesce(c.account_id,p.account_id) account_id,
     coalesce(c.orders,0) current_orders,coalesce(p.orders,0) previous_orders,
     c.sales current_sales,p.sales previous_sales
   FROM current_group c FULL JOIN previous_group p USING(key)
   ORDER BY greatest(coalesce(c.sales,0),coalesce(p.sales,0)) DESC LIMIT 200
 )
 SELECT result||jsonb_build_object('product_movements',coalesce(jsonb_agg(to_jsonb(m)),'[]')) INTO result FROM movements m;

 WITH accounts AS (
   SELECT DISTINCT marketplace,account_id FROM gestao_selected(p_start,p_end,p_filters)
   UNION SELECT DISTINCT marketplace,account_id FROM gestao_selected(previous_start,p_start-1,p_filters)
 ), channels AS (
   SELECT marketplace,account_id,
     gestao_summary(p_start,p_end,current_filters||jsonb_build_object('marketplace',marketplace,'account_id',account_id)) current_stats,
     gestao_summary(previous_start,p_start-1,previous_filters||jsonb_build_object('marketplace',marketplace,'account_id',account_id)) previous_stats
   FROM accounts WHERE account_id IS NOT NULL
 )
 SELECT result||jsonb_build_object('channel_movements',coalesce(jsonb_agg(to_jsonb(c)),'[]')) INTO result FROM channels c;

 IF p_finance THEN
   WITH eligible AS (
     SELECT payload FROM gestao_selected(p_start,p_end,p_filters) WHERE (payload->>'eligible')::boolean
   )
   SELECT result||jsonb_build_object('finance_gaps',jsonb_build_object(
     'orders',count(*),
     'missing_payout',count(*) FILTER(WHERE payload->'finance'->'components'->>'net_payout' IS NULL),
     'missing_taxes',count(*) FILTER(WHERE payload->'finance'->'components'->>'taxes' IS NULL),
     'missing_operating_cost',count(*) FILTER(WHERE payload->'finance'->'components'->>'operating_cost' IS NULL),
     'missing_product_cost',count(*) FILTER(WHERE jsonb_array_length(payload->'items')=0 OR EXISTS (
       SELECT 1 FROM jsonb_array_elements(payload->'items') i
       WHERE i->>'unit_cost' IS NULL OR i->>'quantity' IS NULL)))) INTO result FROM eligible;
 END IF;
 RETURN result;
END $$;

-- Keep the existing database cache: the supplement runs only on a cold revision.
CREATE OR REPLACE FUNCTION public.gestao_report_cached(
 p_start date,p_end date,p_filters jsonb DEFAULT '{}',p_finance boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE key text:=md5(jsonb_build_array(p_start,p_end,p_filters,p_finance)::text); rev bigint; result jsonb;
BEGIN
 rev:=gestao_report_revision(coalesce((p_filters->>'account_id')::integer,0));
 SELECT payload INTO result FROM gestao_report_cache WHERE cache_key=key AND revision=rev AND expires_at>now();
 IF FOUND THEN RETURN result; END IF;
 result:=gestao_report_data(p_start,p_end,p_filters,p_finance);
 result:=result||gestao_report_supplement(p_start,p_end,p_filters,p_finance,result);
 DELETE FROM gestao_report_cache WHERE expires_at<now();
 IF (SELECT count(*) FROM gestao_report_cache)>=256 THEN
   DELETE FROM gestao_report_cache WHERE cache_key IN(SELECT cache_key FROM gestao_report_cache ORDER BY expires_at LIMIT 32);
 END IF;
 INSERT INTO gestao_report_cache VALUES(key,rev,now()+interval '60 seconds',result)
 ON CONFLICT(cache_key) DO UPDATE SET revision=excluded.revision,expires_at=excluded.expires_at,payload=excluded.payload;
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION public.gestao_known_place(text),
 public.gestao_report_supplement(date,date,jsonb,boolean,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_known_place(text),
 public.gestao_report_supplement(date,date,jsonb,boolean,jsonb) TO service_role;

-- The older mirror trigger watches receiver_address; current ML shipments keep
-- delivery geography in destination.shipping_address.
CREATE FUNCTION public.gestao_ml_geography_changed() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF OLD.raw_shipment #> '{destination,shipping_address}' IS NOT DISTINCT FROM
    NEW.raw_shipment #> '{destination,shipping_address}' THEN RETURN NULL; END IF;
 INSERT INTO gestao_outbox(pedido_id)
 SELECT p.id FROM pedidos p WHERE p.pedido_mercadolivre_id=NEW.id
 ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),
   queued_at=now(),lease_until='-infinity'::timestamptz;
 RETURN NULL;
END $$;
CREATE TRIGGER gestao_ml_geography_changed AFTER UPDATE OF raw_shipment
ON public.pedidos_mercadolivre FOR EACH ROW
EXECUTE FUNCTION public.gestao_ml_geography_changed();

-- Explicit, bounded historical repair. Run only after the new projection worker
-- is deployed; the migration itself does not enqueue historical orders.
CREATE FUNCTION public.gestao_requeue_geography(
 p_account integer,p_after integer DEFAULT 0,p_limit integer DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE last_id integer; queued integer;
BEGIN
 WITH batch AS MATERIALIZED (
   SELECT pedido_id FROM gestao_fatos_pedido
   WHERE account_id=p_account AND pedido_id>p_after
     AND (gestao_known_place(payload->>'region') IS NULL OR
          gestao_known_place(payload->>'city') IS NULL)
   ORDER BY pedido_id LIMIT greatest(1,least(p_limit,100))
 ), enqueued AS (
   INSERT INTO gestao_outbox(pedido_id)
   SELECT pedido_id FROM batch
   ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),
     queued_at=now(),lease_until='-infinity'::timestamptz
   RETURNING pedido_id
 )
 SELECT max(pedido_id),count(*) INTO last_id,queued FROM enqueued;
 RETURN jsonb_build_object('last_id',coalesce(last_id,p_after),'queued',queued);
END $$;
REVOKE ALL ON FUNCTION public.gestao_requeue_geography(integer,integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_requeue_geography(integer,integer,integer) TO service_role;
