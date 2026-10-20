-- Account-owned intelligence; existing collections/checkpoints are preserved.
ALTER TABLE public.gestao_coletas ADD COLUMN enabled boolean NOT NULL DEFAULT true;
ALTER TABLE public.gestao_coletas ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.gestao_coletas ADD COLUMN attempts integer NOT NULL DEFAULT 0;
CREATE TABLE public.marketplace_insight_requests (
 account_id integer NOT NULL, resource_id text NOT NULL, capability text NOT NULL,
 pedido_id integer NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
 version text NOT NULL, completed_version text, attempts integer NOT NULL DEFAULT 0,
 next_attempt_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz NOT NULL DEFAULT '-infinity',
 PRIMARY KEY(account_id,resource_id,capability)
);
CREATE INDEX marketplace_insight_due ON public.marketplace_insight_requests(account_id,capability,next_attempt_at);
CREATE INDEX gestao_fatos_account_period ON public.gestao_fatos_pedido(account_id,sold_on,pedido_id);
CREATE INDEX gestao_fatos_buyer_period ON public.gestao_fatos_pedido((payload->>'buyer_key'),sold_on);
CREATE INDEX gestao_fatos_items ON public.gestao_fatos_pedido USING gin((payload->'items') jsonb_path_ops);

CREATE FUNCTION public.marketplace_insight_request_changed() RETURNS trigger LANGUAGE plpgsql
SET search_path=public,pg_temp AS $$
DECLARE cap text; insights jsonb:=NEW.payload->'insights';
BEGIN
 FOR cap IN SELECT jsonb_array_elements_text(coalesce(insights->'enrichments','[]')) LOOP
   INSERT INTO gestao_coletas(account_id,capability,status) VALUES(NEW.account_id,cap,'available') ON CONFLICT(account_id,capability)
   DO UPDATE SET next_attempt_at=least(gestao_coletas.next_attempt_at,now());
   INSERT INTO marketplace_insight_requests(account_id,resource_id,capability,pedido_id,version)
   VALUES(NEW.account_id,insights->>'resource_id',cap,NEW.pedido_id,insights->>'version')
   ON CONFLICT(account_id,resource_id,capability) DO UPDATE
   SET version=excluded.version,attempts=0,next_attempt_at=now()
   WHERE marketplace_insight_requests.version IS DISTINCT FROM excluded.version;
 END LOOP;
 IF coalesce((NEW.payload->'finance'->>'settled')::boolean,false) THEN
 UPDATE marketplace_insight_requests SET attempts=6 WHERE pedido_id=NEW.pedido_id;
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION public.marketplace_insights_listing_batch(p_account integer,p_after integer DEFAULT 0) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY id),'[]') FROM
 (SELECT max(id) id,item_externo_id FROM produto_anuncios WHERE integration_id=p_account AND id>p_after
 AND nullif(item_externo_id,'') IS NOT NULL GROUP BY item_externo_id ORDER BY max(id) LIMIT 5) q;
$$;
REVOKE ALL ON FUNCTION public.marketplace_insights_listing_batch(integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.marketplace_insights_listing_batch(integer,integer) TO service_role;
CREATE TRIGGER marketplace_insight_request_changed AFTER INSERT OR UPDATE ON public.gestao_fatos_pedido
FOR EACH ROW EXECUTE FUNCTION public.marketplace_insight_request_changed();

CREATE FUNCTION public.marketplace_insights_claim(p_account integer,p_capability text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 WITH chosen AS (
   SELECT r.account_id,r.resource_id,r.capability FROM marketplace_insight_requests r
   JOIN gestao_coletas c USING(account_id,capability)
   WHERE r.account_id=p_account AND r.capability=p_capability AND c.enabled AND c.status<>'forbidden'
     AND r.next_attempt_at<=now() AND r.lease_until<now() AND r.attempts<6
   ORDER BY r.next_attempt_at LIMIT 1 FOR UPDATE OF r SKIP LOCKED
 ), claimed AS (
   UPDATE marketplace_insight_requests r SET lease_until=now()+interval '5 minutes'
   FROM chosen c WHERE (r.account_id,r.resource_id,r.capability)=(c.account_id,c.resource_id,c.capability)
   RETURNING r.*
 ) SELECT coalesce(jsonb_agg(jsonb_build_object('id',pedido_id,'marketplace_order_id',resource_id,
     'insight_version',version,'insight_capability',capability)),'[]') INTO result FROM claimed;
 RETURN result;
END $$;
CREATE FUNCTION public.marketplace_insights_complete(p_account integer,p_capability text,p_resource text,p_version text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN
 UPDATE marketplace_insight_requests SET completed_version=p_version,lease_until='-infinity',attempts=attempts+1,
 next_attempt_at=now()+least(30,power(2,attempts))*interval '1 day' WHERE account_id=p_account AND capability=p_capability
 AND resource_id=p_resource AND version=p_version;
 IF FOUND THEN RETURN true; END IF;
 -- A new version arrived during the request; release it without completing the new work.
 UPDATE marketplace_insight_requests SET lease_until='-infinity' WHERE account_id=p_account
 AND capability=p_capability AND resource_id=p_resource;
 RETURN false;
END $$;

-- Database budget adds a conservative ceiling shared across analytical workers.
CREATE TABLE public.marketplace_insight_budget(scope_key text PRIMARY KEY,next_allowed_at timestamptz NOT NULL);
CREATE FUNCTION public.marketplace_insights_budget(p_account integer,p_interval numeric DEFAULT 10,p_scope text DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN
 INSERT INTO marketplace_insight_budget VALUES(coalesce(p_scope,'account:'||p_account),now()) ON CONFLICT DO NOTHING;
 UPDATE marketplace_insight_budget SET next_allowed_at=now()+greatest(1,p_interval)*interval '1 second'
 WHERE scope_key=coalesce(p_scope,'account:'||p_account) AND next_allowed_at<=now(); RETURN FOUND;
END $$;

-- Ignore bookkeeping-only writes without reprocessing their orders.
CREATE OR REPLACE FUNCTION public.gestao_enqueue() RETURNS trigger LANGUAGE plpgsql
SET search_path=public,pg_temp AS $$
DECLARE r jsonb; versions jsonb[]; before_row jsonb; after_row jsonb;
BEGIN
 -- Snapshot items are projected through their canonical item triggers. Raw provider
 -- metadata in snapshots must not recalculate commercial statistics.
 IF TG_TABLE_NAME='pedido_snapshots' THEN RETURN NULL; END IF;
 IF TG_OP='UPDATE' THEN
 before_row:=to_jsonb(OLD)-ARRAY['updated_at','enriched_at','last_synced_at','source_history'];
 after_row:=to_jsonb(NEW)-ARRAY['updated_at','enriched_at','last_synced_at','source_history'];
 IF TG_TABLE_NAME='pedidos_shopee' THEN
 before_row:=jsonb_build_array(before_row->'raw_payload'->'create_time',before_row->'raw_payload'->'buyer_user_id',before_row->'raw_payload'->'recipient_address'->'state',before_row->'raw_payload'->'recipient_address'->'city');
 after_row:=jsonb_build_array(after_row->'raw_payload'->'create_time',after_row->'raw_payload'->'buyer_user_id',after_row->'raw_payload'->'recipient_address'->'state',after_row->'raw_payload'->'recipient_address'->'city');
 ELSIF TG_TABLE_NAME='pedidos_mercadolivre' THEN
 before_row:=jsonb_build_array(before_row->'raw_order'->'date_created',before_row->'raw_order'->'buyer'->'id',before_row->'raw_shipment'->'receiver_address'->'state',before_row->'raw_shipment'->'receiver_address'->'city');
 after_row:=jsonb_build_array(after_row->'raw_order'->'date_created',after_row->'raw_order'->'buyer'->'id',after_row->'raw_shipment'->'receiver_address'->'state',after_row->'raw_shipment'->'receiver_address'->'city');
 ELSIF TG_TABLE_NAME='pedidos' THEN
 SELECT jsonb_object_agg(key,value) INTO before_row FROM jsonb_each(before_row) WHERE key=ANY(ARRAY[
 'id','marketplace_integration_id','marketplace_module_id','origem','data_compra_marketplace','data_venda','created_at',
 'data_pagamento_marketplace','marketplace_lifecycle_stage','marketplace_payment_status','marketplace_order_status','status_original',
 'total_pedido','numero_pedido','pack_id','personalizado','modalidade_logistica','servico_logistico','despachado_em','data_envio_marketplace',
 'data_limite_envio','pedido_shopee_id','pedido_mercadolivre_id','pedido_bling_id','marketplace_order_id','codigo_pedido_externo']);
 SELECT jsonb_object_agg(key,value) INTO after_row FROM jsonb_each(after_row) WHERE key=ANY(ARRAY[
 'id','marketplace_integration_id','marketplace_module_id','origem','data_compra_marketplace','data_venda','created_at',
 'data_pagamento_marketplace','marketplace_lifecycle_stage','marketplace_payment_status','marketplace_order_status','status_original',
 'total_pedido','numero_pedido','pack_id','personalizado','modalidade_logistica','servico_logistico','despachado_em','data_envio_marketplace',
 'data_limite_envio','pedido_shopee_id','pedido_mercadolivre_id','pedido_bling_id','marketplace_order_id','codigo_pedido_externo']);
 ELSIF TG_TABLE_NAME='gestao_financeiro' THEN
 before_row:=before_row-'evidence'; after_row:=after_row-'evidence';
 END IF;
 IF before_row IS NOT DISTINCT FROM after_row THEN RETURN NULL; END IF;
 END IF;
 versions:=CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)]
 WHEN (to_jsonb(OLD)->'pedido_id' IS NOT DISTINCT FROM to_jsonb(NEW)->'pedido_id')
 AND (to_jsonb(OLD)->'item_pedido_id' IS NOT DISTINCT FROM to_jsonb(NEW)->'item_pedido_id')
 AND (to_jsonb(OLD)->'id' IS NOT DISTINCT FROM to_jsonb(NEW)->'id') THEN ARRAY[to_jsonb(NEW)]
 ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH r IN ARRAY versions LOOP
 IF TG_TABLE_NAME='pedidos' THEN
   INSERT INTO gestao_outbox(pedido_id) SELECT (r->>'id')::integer WHERE TG_OP<>'DELETE'
   ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
 ELSIF TG_TABLE_NAME IN ('pedidos_bling','pedidos_shopee','pedidos_mercadolivre') THEN
   INSERT INTO gestao_outbox(pedido_id) SELECT p.id FROM pedidos p WHERE
   (TG_TABLE_NAME='pedidos_bling' AND p.pedido_bling_id=(r->>'id')::bigint) OR
   (TG_TABLE_NAME='pedidos_shopee' AND p.pedido_shopee_id=(r->>'id')::bigint) OR
   (TG_TABLE_NAME='pedidos_mercadolivre' AND p.pedido_mercadolivre_id=(r->>'id')::bigint)
   ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
 ELSE
   INSERT INTO gestao_outbox(pedido_id) SELECT p.id FROM pedidos p WHERE p.id=coalesce((r->>'pedido_id')::integer,
   (SELECT ip.pedido_id FROM itens_pedido ip WHERE ip.id=(r->>'item_pedido_id')::integer))
   ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
 END IF;
 END LOOP; RETURN NULL;
END $$;

-- Catalog mutations enqueue scopes, expanded in bounded worker batches.
CREATE TABLE public.gestao_catalog_scopes (
 scope_key text PRIMARY KEY, produto_id integer, account_id integer, cursor_id integer NOT NULL DEFAULT 0,
 generation bigint NOT NULL DEFAULT nextval('gestao_generation_seq')
);
CREATE OR REPLACE FUNCTION public.gestao_catalog_changed() RETURNS trigger LANGUAGE plpgsql
SET search_path=public,pg_temp AS $$
DECLARE r jsonb; rows jsonb[]; pid integer; aid integer; key text;
BEGIN
 rows:=CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH r IN ARRAY rows LOOP
  pid:=CASE WHEN TG_TABLE_NAME='produtos' THEN (r->>'id')::integer ELSE (r->>'produto_id')::integer END;
  aid:=CASE WHEN TG_TABLE_NAME='installed_integrations' THEN (r->>'id')::integer ELSE (r->>'integration_id')::integer END;
  IF pid IS NULL AND aid IS NULL THEN CONTINUE; END IF;
  key:=coalesce(pid::text,'*')||':'||coalesce(aid::text,'*');
  INSERT INTO gestao_catalog_scopes(scope_key,produto_id,account_id) VALUES(key,pid,aid)
  ON CONFLICT(scope_key) DO UPDATE SET cursor_id=0,generation=nextval('gestao_generation_seq');
 END LOOP; RETURN NULL;
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['produtos','produto_anuncios','gestao_custos'] LOOP
 EXECUTE format('DROP TRIGGER gestao_catalog_changed ON public.%I',t);
 EXECUTE format('CREATE TRIGGER gestao_catalog_changed AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.gestao_catalog_changed()',t);
 END LOOP;
END $$;
DROP TRIGGER gestao_account_renamed ON public.installed_integrations;
CREATE TRIGGER gestao_account_renamed AFTER UPDATE OF instance_name ON public.installed_integrations
FOR EACH ROW EXECUTE FUNCTION public.gestao_catalog_changed();
CREATE FUNCTION public.gestao_expand_scopes() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path=public,pg_temp AS $$
DECLARE s gestao_catalog_scopes; ids integer[]; n integer:=0;
BEGIN
 FOR s IN SELECT * FROM gestao_catalog_scopes ORDER BY scope_key LIMIT 5 FOR UPDATE SKIP LOCKED LOOP
 SELECT array_agg(id) INTO ids FROM (SELECT p.id FROM pedidos p WHERE p.id>s.cursor_id
 AND (s.account_id IS NULL OR p.marketplace_integration_id=s.account_id)
 AND (s.produto_id IS NULL OR EXISTS(SELECT 1 FROM itens_pedido i WHERE i.pedido_id=p.id AND i.produto_id=s.produto_id)
   OR EXISTS(SELECT 1 FROM itens_pedido i JOIN produtos product ON product.id=s.produto_id
     WHERE i.pedido_id=p.id AND lower(trim(i.sku_externo))=lower(trim(to_jsonb(product)->>'sku')) AND nullif(trim(i.sku_externo),'') IS NOT NULL)
   OR (s.account_id IS NOT NULL AND EXISTS(SELECT 1 FROM itens_pedido i JOIN produto_anuncios listing
     ON to_jsonb(listing)->>'item_externo_id'=to_jsonb(i)->>'item_externo_id'
     WHERE i.pedido_id=p.id AND (to_jsonb(listing)->>'produto_id')::integer=s.produto_id
     AND (to_jsonb(listing)->>'integration_id')::integer=s.account_id))
   OR EXISTS(SELECT 1 FROM gestao_fatos_pedido f WHERE f.pedido_id=p.id AND f.payload->'items' @> jsonb_build_array(jsonb_build_object('product_id',s.produto_id))))
 ORDER BY p.id LIMIT 100) q;
 IF ids IS NULL THEN DELETE FROM gestao_catalog_scopes WHERE scope_key=s.scope_key;
 ELSE
 INSERT INTO gestao_outbox(pedido_id) SELECT unnest(ids) ON CONFLICT(pedido_id)
 DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
 UPDATE gestao_catalog_scopes SET cursor_id=ids[array_length(ids,1)] WHERE scope_key=s.scope_key;
 n:=n+array_length(ids,1);
 END IF;
 END LOOP; RETURN n;
END $$;

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['marketplace_insight_requests','marketplace_insight_budget','gestao_catalog_scopes'] LOOP
 EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('REVOKE ALL ON public.%I FROM anon,authenticated',t);
 EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_insights_claim(integer,text),public.marketplace_insights_complete(integer,text,text,text),
 public.marketplace_insights_budget(integer,numeric,text),public.gestao_expand_scopes() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.marketplace_insights_claim(integer,text),public.marketplace_insights_complete(integer,text,text,text),
 public.marketplace_insights_budget(integer,numeric,text),public.gestao_expand_scopes() TO service_role;

CREATE FUNCTION public.marketplace_insights_coverage(p_account integer) RETURNS jsonb LANGUAGE sql STABLE
SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT jsonb_build_object('orders',count(*),'from',min(sold_on),'to',max(sold_on),'last_synced_at',max(synced_at),
 'missing_buyer',count(*) FILTER(WHERE payload->>'buyer_key' IS NULL),
 'missing_geography',count(*) FILTER(WHERE payload->>'region' IS NULL),
 'pending',(SELECT count(*) FROM gestao_outbox o JOIN pedidos p ON p.id=o.pedido_id WHERE p.marketplace_integration_id=p_account),
 'oldest_pending_at',(SELECT min(o.queued_at) FROM gestao_outbox o JOIN pedidos p ON p.id=o.pedido_id WHERE p.marketplace_integration_id=p_account),
 'enrichment_pending',(SELECT count(*) FROM marketplace_insight_requests WHERE account_id=p_account AND completed_version IS DISTINCT FROM version))
 FROM gestao_fatos_pedido WHERE account_id=p_account;
$$;
CREATE FUNCTION public.marketplace_insights_backfill(p_account integer,p_capability text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN
 INSERT INTO marketplace_insight_checkpoint_history(account_id,capability,checkpoint)
 SELECT account_id,capability,checkpoint FROM gestao_coletas WHERE account_id=p_account AND capability=p_capability;
 UPDATE marketplace_insight_requests SET attempts=0,next_attempt_at=now()
 WHERE account_id=p_account AND capability=p_capability;
 UPDATE gestao_coletas SET checkpoint=CASE WHEN p_capability IN ('shopee_escrow','ml_billing') THEN checkpoint
 ELSE jsonb_build_object('backfill_requested_at',now()) END
 WHERE account_id=p_account AND capability=p_capability;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_insights_coverage(integer),public.marketplace_insights_backfill(integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.marketplace_insights_coverage(integer),public.marketplace_insights_backfill(integer,text) TO service_role;

CREATE FUNCTION public.marketplace_insights_store_finance(p_account integer,p_capability text,p_resource text,p_version text,
 p_components jsonb,p_settled boolean,p_evidence jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE pid integer;
BEGIN
 -- Serialize with canonical order updates, then inspect the outbox using the
 -- fresh command snapshot. No order lock is held during the provider HTTP call.
 PERFORM 1 FROM pedidos p WHERE p.id=(SELECT r.pedido_id FROM marketplace_insight_requests r
 WHERE r.account_id=p_account AND r.capability=p_capability AND r.resource_id=p_resource) FOR UPDATE;
 SELECT r.pedido_id INTO pid FROM marketplace_insight_requests r JOIN gestao_fatos_pedido f ON f.pedido_id=r.pedido_id
 WHERE r.account_id=p_account AND r.capability=p_capability AND r.resource_id=p_resource AND r.version=p_version
 AND f.account_id=p_account AND f.payload->'insights'->>'resource_id'=p_resource
 AND f.payload->'insights'->>'version'=p_version
 AND NOT EXISTS(SELECT 1 FROM gestao_outbox o WHERE o.pedido_id=r.pedido_id) FOR UPDATE OF r;
 IF NOT FOUND THEN
 UPDATE marketplace_insight_requests SET lease_until='-infinity' WHERE account_id=p_account AND capability=p_capability AND resource_id=p_resource;
 RETURN false;
 END IF;
 INSERT INTO gestao_financeiro(pedido_id,components,source,settled,evidence)
 VALUES(pid,p_components,p_capability,p_settled,p_evidence) ON CONFLICT(pedido_id) DO UPDATE
 SET components=gestao_financeiro.components||excluded.components,source=excluded.source,
 settled=excluded.settled,evidence=excluded.evidence,updated_at=now() WHERE gestao_financeiro.source<>'manual';
 PERFORM marketplace_insights_complete(p_account,p_capability,p_resource,p_version);
 IF p_settled THEN UPDATE marketplace_insight_requests SET attempts=6 WHERE account_id=p_account AND capability=p_capability AND resource_id=p_resource; END IF;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_insights_store_finance(integer,text,text,text,jsonb,boolean,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.marketplace_insights_store_finance(integer,text,text,text,jsonb,boolean,jsonb) TO service_role;

CREATE TABLE public.marketplace_insight_checkpoint_history (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,account_id integer NOT NULL,capability text NOT NULL,
 checkpoint jsonb NOT NULL,recorded_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.marketplace_insight_checkpoint_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.marketplace_insight_checkpoint_history FROM anon,authenticated;
GRANT ALL ON public.marketplace_insight_checkpoint_history TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.marketplace_insight_checkpoint_history_id_seq TO service_role;

CREATE FUNCTION public.marketplace_insights_release(p_account integer,p_capability text) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 UPDATE marketplace_insight_requests SET lease_until='-infinity' WHERE account_id=p_account AND capability=p_capability;
$$;
REVOKE ALL ON FUNCTION public.marketplace_insights_release(integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.marketplace_insights_release(integer,text) TO service_role;

-- Existing sync replaces Shopee item IDs even for an identical snapshot. Avoid
-- that work (and preserve customization references) on repeated notifications.
DO $$ BEGIN
 IF to_regprocedure('public.sync_marketplace_snapshot_items()') IS NOT NULL THEN
 DROP TRIGGER IF EXISTS trg_sync_marketplace_snapshot_items ON public.pedido_snapshots;
 CREATE TRIGGER trg_sync_marketplace_snapshot_items AFTER INSERT ON public.pedido_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.sync_marketplace_snapshot_items();
 CREATE TRIGGER trg_sync_marketplace_snapshot_items_changed AFTER UPDATE OF items,identity ON public.pedido_snapshots
 FOR EACH ROW WHEN(OLD.items IS DISTINCT FROM NEW.items OR OLD.identity->>'ingest_source' IS DISTINCT FROM NEW.identity->>'ingest_source')
 EXECUTE FUNCTION public.sync_marketplace_snapshot_items();
 END IF;
END $$;
