-- Management projections are service-only. HTTP authorization lives in gestao.py.
CREATE SEQUENCE public.gestao_generation_seq;
CREATE TABLE public.gestao_outbox (
  pedido_id integer PRIMARY KEY REFERENCES public.pedidos(id) ON DELETE CASCADE,
  generation bigint NOT NULL DEFAULT nextval('public.gestao_generation_seq'),
  lease_until timestamptz NOT NULL DEFAULT '-infinity',
  queued_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.gestao_fatos_pedido (
  pedido_id integer PRIMARY KEY REFERENCES public.pedidos(id) ON DELETE CASCADE,
  sold_on date NOT NULL,
  account_id integer,
  marketplace text NOT NULL,
  payload jsonb NOT NULL,
  synced_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX gestao_fatos_periodo ON public.gestao_fatos_pedido(sold_on, account_id);
CREATE TABLE public.gestao_custos (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  produto_id integer NOT NULL REFERENCES public.produtos(id) ON DELETE CASCADE,
  valid_from timestamptz NOT NULL,
  unit_cost numeric NOT NULL CHECK(unit_cost >= 0),
  source text NOT NULL CHECK(source IN ('cadastro','ficha_tecnica','realizado','manual')),
  estimated boolean NOT NULL DEFAULT true,
  UNIQUE(produto_id, valid_from)
);
CREATE TABLE public.gestao_financeiro (
  pedido_id integer PRIMARY KEY REFERENCES public.pedidos(id) ON DELETE CASCADE,
  -- Values are absolute components, never an additive duplicate of net payout.
  components jsonb NOT NULL DEFAULT '{}',
  source text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}',
  settled boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.gestao_metricas_anuncio (
  account_id integer NOT NULL,
  resource_id text NOT NULL,
  day date NOT NULL,
  kind text NOT NULL CHECK(kind IN ('visits','ads','counter')),
  metrics jsonb NOT NULL,
  source text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(account_id,resource_id,day,kind)
);
CREATE TABLE public.gestao_financeiro_historico (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pedido_id integer NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
  snapshot jsonb NOT NULL,
  fingerprint text NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(pedido_id,fingerprint)
);
CREATE FUNCTION public.gestao_financial_revision() RETURNS trigger LANGUAGE plpgsql
SET search_path=public,pg_temp AS $$
DECLARE value jsonb:=to_jsonb(NEW)-'updated_at';
BEGIN
  INSERT INTO gestao_financeiro_historico(pedido_id,snapshot,fingerprint)
  VALUES(NEW.pedido_id,value,md5(value::text)) ON CONFLICT DO NOTHING;
  RETURN NULL;
END $$;
CREATE TRIGGER gestao_financial_revision AFTER INSERT OR UPDATE ON public.gestao_financeiro
FOR EACH ROW EXECUTE FUNCTION public.gestao_financial_revision();
CREATE TABLE public.gestao_coletas (
  account_id integer NOT NULL,
  capability text NOT NULL,
  status text NOT NULL CHECK(status IN ('pending','available','forbidden','failed')),
  checkpoint jsonb NOT NULL DEFAULT '{}',
  error_code text,
  lease_until timestamptz NOT NULL DEFAULT '-infinity',
  checked_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(account_id,capability)
);
CREATE TABLE public.gestao_metas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  month date NOT NULL CHECK(extract(day FROM month)=1),
  account_id integer NOT NULL DEFAULT 0,
  metric text NOT NULL CHECK(metric IN ('sales','contribution','orders')),
  target numeric NOT NULL CHECK(target > 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(month,account_id,metric)
);
CREATE TABLE public.gestao_apontamentos (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_key uuid NOT NULL UNIQUE,
  pedido_id integer NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
  stage text NOT NULL CHECK(stage IN ('personalizacao','producao','despacho','retrabalho','perda')),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  quantity numeric CHECK(quantity >= 0),
  cost numeric CHECK(cost >= 0),
  duration_minutes numeric CHECK(duration_minutes >= 0)
);

CREATE FUNCTION public.gestao_enqueue() RETURNS trigger LANGUAGE plpgsql
SET search_path = public, pg_temp AS $$
DECLARE r jsonb; versions jsonb[];
BEGIN
  versions := CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)]
                   WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)]
                   ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
  FOREACH r IN ARRAY versions LOOP
  IF TG_TABLE_NAME='pedidos' THEN
    INSERT INTO gestao_outbox(pedido_id) SELECT (r->>'id')::integer WHERE TG_OP<>'DELETE'
    ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
  ELSIF TG_TABLE_NAME IN ('pedidos_bling','pedidos_shopee','pedidos_mercadolivre') THEN
    INSERT INTO gestao_outbox(pedido_id)
    SELECT p.id FROM pedidos p WHERE
      (TG_TABLE_NAME='pedidos_bling' AND p.pedido_bling_id=(r->>'id')::bigint) OR
      (TG_TABLE_NAME='pedidos_shopee' AND p.pedido_shopee_id=(r->>'id')::bigint) OR
      (TG_TABLE_NAME='pedidos_mercadolivre' AND p.pedido_mercadolivre_id=(r->>'id')::bigint)
    ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
  ELSE
    INSERT INTO gestao_outbox(pedido_id)
    SELECT p.id FROM pedidos p WHERE p.id=coalesce((r->>'pedido_id')::integer,
      (SELECT ip.pedido_id FROM itens_pedido ip WHERE ip.id=(r->>'item_pedido_id')::integer))
    ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
  END IF;
  END LOOP;
  RETURN NULL;
END $$;
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['pedidos','itens_pedido','pedido_snapshots','pedidos_bling',
    'pedidos_shopee','pedidos_mercadolivre','personalizacoes_pedido','mercadolivre_personalizations',
    'gestao_financeiro','gestao_apontamentos'] LOOP
    EXECUTE format('CREATE TRIGGER gestao_changed AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.gestao_enqueue()',t);
  END LOOP;
END $$;
CREATE FUNCTION public.gestao_catalog_changed() RETURNS trigger LANGUAGE plpgsql
SET search_path = public, pg_temp AS $$ BEGIN
  INSERT INTO gestao_outbox(pedido_id) SELECT id FROM pedidos
  ON CONFLICT(pedido_id) DO UPDATE SET generation=nextval('gestao_generation_seq'),queued_at=now();
  RETURN NULL;
END $$;
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['produtos','produto_anuncios','gestao_custos'] LOOP
    EXECUTE format('CREATE TRIGGER gestao_catalog_changed AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.gestao_catalog_changed()',t);
  END LOOP;
END $$;
CREATE TRIGGER gestao_account_renamed AFTER UPDATE OF instance_name ON public.installed_integrations
FOR EACH STATEMENT EXECUTE FUNCTION public.gestao_catalog_changed();
CREATE FUNCTION public.gestao_record_cost() RETURNS trigger LANGUAGE plpgsql
SET search_path = public, pg_temp AS $$ BEGIN
  IF NEW.preco_custo IS NOT NULL AND (TG_OP='INSERT' OR NEW.preco_custo IS DISTINCT FROM OLD.preco_custo) THEN
    INSERT INTO gestao_custos(produto_id,valid_from,unit_cost,source,estimated)
    VALUES(NEW.id,clock_timestamp(),NEW.preco_custo,'cadastro',true);
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER gestao_record_cost AFTER INSERT OR UPDATE OF preco_custo ON public.produtos
FOR EACH ROW EXECUTE FUNCTION public.gestao_record_cost();

CREATE FUNCTION public.gestao_claim(p_limit integer DEFAULT 100) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE result jsonb;
BEGIN
  WITH chosen AS (
    SELECT pedido_id FROM gestao_outbox WHERE lease_until<now()
    ORDER BY queued_at,pedido_id LIMIT greatest(1,least(p_limit,250)) FOR UPDATE SKIP LOCKED
  ), claimed AS (
    UPDATE gestao_outbox o SET lease_until=now()+interval '5 minutes'
    FROM chosen c WHERE c.pedido_id=o.pedido_id RETURNING o.*
  ) SELECT coalesce(jsonb_agg(jsonb_build_object(
    'generation',c.generation,'order',to_jsonb(p),'account_name',a.instance_name,
    'snapshot',to_jsonb(s),'bling',b.raw_payload,'shopee',sh.raw_payload,
    'ml',m.raw_order,'shipment',m.raw_shipment,
    'items',(SELECT coalesce(jsonb_agg(to_jsonb(ip) ORDER BY ip.id),'[]') FROM itens_pedido ip WHERE ip.pedido_id=p.id),
    'names',(SELECT coalesce(jsonb_agg(n),'[]') FROM (
      SELECT to_jsonb(x)||jsonb_build_object('provider','shopee') AS n FROM personalizacoes_pedido x
      JOIN itens_pedido ip ON ip.id=x.item_pedido_id WHERE ip.pedido_id=p.id
      UNION ALL SELECT to_jsonb(x)||jsonb_build_object('provider','mercadolivre') FROM mercadolivre_personalizations x WHERE x.pedido_id=p.id
    ) names),
    'finance',(SELECT to_jsonb(f) FROM gestao_financeiro f WHERE f.pedido_id=p.id),
    'events',(SELECT coalesce(jsonb_agg(to_jsonb(e)),'[]') FROM gestao_apontamentos e WHERE e.pedido_id=p.id)
  )),'[]') INTO result
  FROM claimed c JOIN pedidos p ON p.id=c.pedido_id
  LEFT JOIN installed_integrations a ON a.id=p.marketplace_integration_id
  LEFT JOIN pedido_snapshots s ON s.pedido_id=p.id
  LEFT JOIN pedidos_bling b ON b.id=p.pedido_bling_id
  LEFT JOIN pedidos_shopee sh ON sh.id=p.pedido_shopee_id
  LEFT JOIN pedidos_mercadolivre m ON m.id=p.pedido_mercadolivre_id;
  RETURN result;
END $$;
CREATE FUNCTION public.gestao_finish(p_rows jsonb) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r jsonb; n integer:=0;
BEGIN
  FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
    PERFORM 1 FROM gestao_outbox WHERE pedido_id=(r->>'id')::integer
      AND generation=(r->>'generation')::bigint FOR UPDATE;
    IF FOUND THEN
      INSERT INTO gestao_fatos_pedido(pedido_id,sold_on,account_id,marketplace,payload)
      VALUES((r->>'id')::integer,(r->>'sold_on')::date,(r->>'account_id')::integer,r->>'marketplace',r-'generation')
      ON CONFLICT(pedido_id) DO UPDATE SET sold_on=excluded.sold_on,account_id=excluded.account_id,
        marketplace=excluded.marketplace,payload=excluded.payload,synced_at=now();
      DELETE FROM gestao_outbox WHERE pedido_id=(r->>'id')::integer AND generation=(r->>'generation')::bigint;
      n:=n+1;
    ELSE
      UPDATE gestao_outbox SET lease_until='-infinity' WHERE pedido_id=(r->>'id')::integer;
    END IF;
  END LOOP;
  RETURN n;
END $$;

INSERT INTO public.gestao_outbox(pedido_id) SELECT id FROM public.pedidos;
INSERT INTO public.recursos(nome,descricao) VALUES
 ('gestao','Indicadores comerciais e planejamento'),
 ('gestao_financeiro','Rentabilidade, custos e conciliação'),
 ('gestao_detalhes','Pedidos e exportações da área Gestão') ON CONFLICT(nome) DO NOTHING;
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['gestao_outbox','gestao_fatos_pedido','gestao_custos','gestao_financeiro',
    'gestao_metricas_anuncio','gestao_coletas','gestao_metas','gestao_apontamentos','gestao_financeiro_historico'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated',t);
    EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
  END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.gestao_claim(integer), public.gestao_finish(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_claim(integer), public.gestao_finish(jsonb) TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.gestao_generation_seq,public.gestao_custos_id_seq,
 public.gestao_metas_id_seq,public.gestao_apontamentos_id_seq,public.gestao_financeiro_historico_id_seq TO service_role;
CREATE FUNCTION public.gestao_collection_lease(p_account integer,p_capability text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN
  INSERT INTO gestao_coletas(account_id,capability,status) VALUES(p_account,p_capability,'pending') ON CONFLICT DO NOTHING;
  UPDATE gestao_coletas SET lease_until=now()+interval '5 minutes'
  WHERE account_id=p_account AND capability=p_capability AND lease_until<now();
  RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.gestao_collection_lease(integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gestao_collection_lease(integer,text) TO service_role;
