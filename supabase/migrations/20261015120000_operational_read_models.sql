-- Read models for the two slow operational screens.
-- Source writes enqueue compact, coalesced events in the same transaction.

CREATE TABLE IF NOT EXISTS public.operational_read_model_outbox (
    event_key text PRIMARY KEY,
    personalized boolean NOT NULL DEFAULT false,
    dispatch boolean NOT NULL DEFAULT false,
    backfill boolean NOT NULL DEFAULT false,
    dispatch_calendar boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.operational_read_model_outbox
    ADD COLUMN IF NOT EXISTS dispatch_calendar boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS operational_read_model_outbox_created_idx
    ON public.operational_read_model_outbox (created_at);

CREATE TABLE IF NOT EXISTS public.shopee_personalization_read_model (
    id integer PRIMARY KEY,
    marketplace_integration_id integer,
    numero_pedido text,
    numero_loja text,
    nome_cliente text,
    buyer_username text,
    data_pedido timestamptz,
    has_chat_messages boolean NOT NULL DEFAULT false,
    has_buyer_message boolean NOT NULL DEFAULT false,
    needs_ai_processing boolean NOT NULL DEFAULT false,
    has_identified_name boolean NOT NULL DEFAULT false,
    has_no_name boolean NOT NULL DEFAULT false,
    ai_status text,
    detalhes jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS shopee_personalization_read_model_page_idx
    ON public.shopee_personalization_read_model
       (marketplace_integration_id, data_pedido DESC, id DESC);
CREATE EXTENSION IF NOT EXISTS pg_trgm;
DO $$
DECLARE opclass_schema text;
BEGIN
  SELECT n.nspname INTO opclass_schema
    FROM pg_catalog.pg_opclass o
    JOIN pg_catalog.pg_namespace n ON n.oid=o.opcnamespace
    JOIN pg_catalog.pg_am am ON am.oid=o.opcmethod
   WHERE o.opcname='gin_trgm_ops' AND am.amname='gin'
   LIMIT 1;
  IF opclass_schema IS NULL THEN
    RAISE EXCEPTION 'pg_trgm gin_trgm_ops operator class is unavailable';
  END IF;
  EXECUTE format('CREATE INDEX IF NOT EXISTS shopee_personalization_read_model_numero_trgm_idx ON public.shopee_personalization_read_model USING gin (numero_pedido %I.gin_trgm_ops)',opclass_schema);
  EXECUTE format('CREATE INDEX IF NOT EXISTS shopee_personalization_read_model_store_trgm_idx ON public.shopee_personalization_read_model USING gin (numero_loja %I.gin_trgm_ops)',opclass_schema);
  EXECUTE format('CREATE INDEX IF NOT EXISTS shopee_personalization_read_model_name_trgm_idx ON public.shopee_personalization_read_model USING gin (nome_cliente %I.gin_trgm_ops)',opclass_schema);
  EXECUTE format('CREATE INDEX IF NOT EXISTS shopee_personalization_read_model_username_trgm_idx ON public.shopee_personalization_read_model USING gin (buyer_username %I.gin_trgm_ops)',opclass_schema);
END $$;

CREATE TABLE IF NOT EXISTS public.shopee_personalization_read_model_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    backfill_complete boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.operational_read_model_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    personalized_projection_enabled boolean NOT NULL DEFAULT true,
    dispatch_snapshot_enabled boolean NOT NULL DEFAULT true,
    dispatch_windows_enabled boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.operational_read_model_config(singleton)
VALUES (true) ON CONFLICT (singleton) DO NOTHING;
INSERT INTO public.shopee_personalization_read_model_state(singleton, backfill_complete)
VALUES (true, false) ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.despacho_contexto_read_model (
    data date PRIMARY KEY,
    payload jsonb NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    valid_until timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS public.despacho_grupos_janelas_read_model (
    integration_id integer,
    modalidade_id integer NOT NULL,
    data_inicio date NOT NULL,
    data_fim date NOT NULL
);
CREATE INDEX IF NOT EXISTS despacho_grupos_janelas_lookup_idx
    ON public.despacho_grupos_janelas_read_model
       ((COALESCE(integration_id, -1)), modalidade_id, data_inicio, data_fim);
CREATE TABLE IF NOT EXISTS public.despacho_janelas_read_model (
    integration_id integer,
    modalidade_id integer NOT NULL,
    dia date NOT NULL,
    coleta_em timestamptz,
    payload jsonb
);
CREATE INDEX IF NOT EXISTS despacho_janelas_read_model_lookup_idx
    ON public.despacho_janelas_read_model
       ((COALESCE(integration_id, -1)), modalidade_id, dia, coleta_em);
CREATE TABLE IF NOT EXISTS public.despacho_janelas_read_model_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    data_inicio date NOT NULL,
    data_fim date NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

REVOKE ALL ON public.operational_read_model_outbox,
    public.shopee_personalization_read_model,
    public.shopee_personalization_read_model_state,
    public.operational_read_model_config,
    public.despacho_contexto_read_model,
    public.despacho_grupos_janelas_read_model,
    public.despacho_janelas_read_model,
    public.despacho_janelas_read_model_state FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.operational_read_model_outbox,
    public.shopee_personalization_read_model,
    public.shopee_personalization_read_model_state,
    public.operational_read_model_config,
    public.despacho_contexto_read_model,
    public.despacho_grupos_janelas_read_model,
    public.despacho_janelas_read_model,
    public.despacho_janelas_read_model_state TO service_role;

CREATE OR REPLACE FUNCTION public.enqueue_operational_read_model_event(
    p_key text, p_personalized boolean DEFAULT false,
    p_dispatch boolean DEFAULT false, p_backfill boolean DEFAULT false,
    p_dispatch_calendar boolean DEFAULT false
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    INSERT INTO public.operational_read_model_outbox(event_key, personalized, dispatch, backfill, dispatch_calendar)
    VALUES (p_key, p_personalized, p_dispatch, p_backfill, p_dispatch_calendar)
    ON CONFLICT (event_key) DO UPDATE SET
        personalized = operational_read_model_outbox.personalized OR EXCLUDED.personalized,
        dispatch = operational_read_model_outbox.dispatch OR EXCLUDED.dispatch,
        backfill = operational_read_model_outbox.backfill OR EXCLUDED.backfill,
        dispatch_calendar = operational_read_model_outbox.dispatch_calendar OR EXCLUDED.dispatch_calendar;
$$;

CREATE OR REPLACE FUNCTION public.operational_read_model_source_trigger()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    r jsonb;
    v_id text;
    v_username text;
    v_order_sn text;
    v_item_id text;
BEGIN
    IF TG_OP = 'DELETE' THEN r := to_jsonb(OLD); ELSE r := to_jsonb(NEW); END IF;
    IF TG_TABLE_NAME = 'pedidos' THEN
        v_id := r ->> 'id';
        IF v_id IS NOT NULL THEN
            PERFORM public.enqueue_operational_read_model_event('order:' || v_id, true, true);
        END IF;
    ELSIF TG_TABLE_NAME = 'itens_pedido' THEN
        FOR r IN SELECT value FROM jsonb_array_elements(
            CASE WHEN TG_OP='UPDATE' THEN jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) ELSE jsonb_build_array(r) END
        ) AS entry(value) LOOP
          v_id := r ->> 'pedido_id';
          IF v_id IS NOT NULL THEN
              PERFORM public.enqueue_operational_read_model_event('order:' || v_id, true, true);
          END IF;
        END LOOP;
    ELSIF TG_TABLE_NAME = 'personalizacoes_pedido' THEN
        FOR r IN SELECT value FROM jsonb_array_elements(
            CASE WHEN TG_OP='UPDATE' THEN jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) ELSE jsonb_build_array(r) END
        ) AS entry(value) LOOP
          v_item_id := r ->> 'item_pedido_id';
          v_order_sn := r ->> 'shopee_order_sn';
          IF v_item_id IS NOT NULL THEN
              PERFORM public.enqueue_operational_read_model_event('item:' || v_item_id, true, false);
          ELSIF NULLIF(v_order_sn, '') IS NOT NULL THEN
              PERFORM public.enqueue_operational_read_model_event('sn:' || v_order_sn, true, false);
          END IF;
        END LOOP;
    ELSIF TG_TABLE_NAME = 'mensagem_chat_shopee' THEN
        FOR r IN SELECT value FROM jsonb_array_elements(
            CASE WHEN TG_OP='UPDATE' THEN jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) ELSE jsonb_build_array(r) END
        ) AS entry(value) LOOP
          FOREACH v_username IN ARRAY ARRAY[r ->> 'from_user_name', r ->> 'to_user_name'] LOOP
              IF NULLIF(v_username, '') IS NOT NULL THEN
                  PERFORM public.enqueue_operational_read_model_event('user:' || v_username, true, false);
              END IF;
          END LOOP;
        END LOOP;
    ELSIF TG_TABLE_NAME = 'logs_execucao_ia' THEN
        FOR r IN SELECT value FROM jsonb_array_elements(
            CASE WHEN TG_OP='UPDATE' THEN jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) ELSE jsonb_build_array(r) END
        ) AS entry(value) LOOP
          v_order_sn := r ->> 'order_sn';
          IF NULLIF(v_order_sn, '') IS NOT NULL THEN
              PERFORM public.enqueue_operational_read_model_event('sn:' || v_order_sn, true, false);
          END IF;
        END LOOP;
    ELSE
        PERFORM public.enqueue_operational_read_model_event('dispatch:global', false, true, false, true);
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;

DROP TRIGGER IF EXISTS operational_read_model_pedidos ON public.pedidos;
CREATE TRIGGER operational_read_model_pedidos AFTER INSERT OR UPDATE OR DELETE ON public.pedidos
FOR EACH ROW EXECUTE FUNCTION public.operational_read_model_source_trigger();
DROP TRIGGER IF EXISTS operational_read_model_itens ON public.itens_pedido;
CREATE TRIGGER operational_read_model_itens AFTER INSERT OR UPDATE OR DELETE ON public.itens_pedido
FOR EACH ROW EXECUTE FUNCTION public.operational_read_model_source_trigger();
DROP TRIGGER IF EXISTS operational_read_model_personalizacoes ON public.personalizacoes_pedido;
CREATE TRIGGER operational_read_model_personalizacoes AFTER INSERT OR UPDATE OR DELETE ON public.personalizacoes_pedido
FOR EACH ROW EXECUTE FUNCTION public.operational_read_model_source_trigger();
DROP TRIGGER IF EXISTS operational_read_model_chat ON public.mensagem_chat_shopee;
CREATE TRIGGER operational_read_model_chat AFTER INSERT OR UPDATE OR DELETE ON public.mensagem_chat_shopee
FOR EACH ROW EXECUTE FUNCTION public.operational_read_model_source_trigger();
DROP TRIGGER IF EXISTS operational_read_model_ia ON public.logs_execucao_ia;
CREATE TRIGGER operational_read_model_ia AFTER INSERT OR UPDATE OR DELETE ON public.logs_execucao_ia
FOR EACH ROW EXECUTE FUNCTION public.operational_read_model_source_trigger();

-- Logistics inputs invalidate the one shared dispatch snapshot.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['logistica_agendas','logistica_excecoes',
      'regras_logisticas_integracao','modalidades_logisticas',
      'regras_classificacao_modalidade','regra_logistica_modalidades',
      'modalidade_config_conta'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('DROP TRIGGER IF EXISTS operational_read_model_dispatch ON public.%I', t);
      EXECUTE format('CREATE TRIGGER operational_read_model_dispatch AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.operational_read_model_source_trigger()', t);
    END IF;
  END LOOP;
END $$;

-- Initial population is seeded by the worker in bounded batches. This keeps
-- the migration itself independent of the production order table's size.

CREATE OR REPLACE FUNCTION public.rebuild_shopee_personalization_read_model(p_ids integer[])
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_count integer;
BEGIN
    WITH source AS MATERIALIZED (
        SELECT d.*, p.marketplace_integration_id,
               EXISTS (
                 SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(d.itens)='array' THEN d.itens ELSE '[]'::jsonb END) i(value)
                 CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(i.value->'personalizations')='array' THEN i.value->'personalizations' ELSE '[]'::jsonb END) x(value)
                 WHERE NULLIF(trim(COALESCE(x.value->>'customization_name',x.value->>'customization_initial','')), '') IS NOT NULL
               ) AS has_identified_name,
               (upper(COALESCE(d.ai_status,'')) = 'NO_PERSONALIZATION_FOUND' OR EXISTS (
                 SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(d.itens)='array' THEN d.itens ELSE '[]'::jsonb END) i(value)
                 CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(i.value->'personalizations')='array' THEN i.value->'personalizations' ELSE '[]'::jsonb END) x(value)
                 WHERE upper(COALESCE(x.value->>'status',''))='NO_PERSONALIZATION_FOUND'
                    OR (upper(COALESCE(x.value->>'status',''))='SUCCESS' AND NULLIF(trim(COALESCE(x.value->>'customization_name',x.value->>'customization_initial','')), '') IS NULL)
               )) AS has_no_name
          FROM public.view_vendas_personalizadas_v3 d
          JOIN public.pedidos p ON p.id=d.id
         WHERE d.id = ANY(COALESCE(p_ids, ARRAY[]::integer[]))
    ), saved AS (
      INSERT INTO public.shopee_personalization_read_model(
        id, marketplace_integration_id, numero_pedido, numero_loja, nome_cliente,
        buyer_username, data_pedido, has_chat_messages, has_buyer_message,
        needs_ai_processing, has_identified_name, has_no_name, ai_status, detalhes, updated_at
      )
      SELECT id, marketplace_integration_id, numero_pedido, numero_loja, nome_cliente,
             buyer_username, data_pedido, COALESCE(has_chat_messages,false),
             COALESCE(has_buyer_message,false), COALESCE(needs_ai_processing,false),
             has_identified_name, has_no_name, ai_status,
             to_jsonb(source) - ARRAY['has_identified_name','has_no_name'], now()
        FROM source
      ON CONFLICT (id) DO UPDATE SET
        marketplace_integration_id=EXCLUDED.marketplace_integration_id,
        numero_pedido=EXCLUDED.numero_pedido, numero_loja=EXCLUDED.numero_loja,
        nome_cliente=EXCLUDED.nome_cliente, buyer_username=EXCLUDED.buyer_username,
        data_pedido=EXCLUDED.data_pedido, has_chat_messages=EXCLUDED.has_chat_messages,
        has_buyer_message=EXCLUDED.has_buyer_message, needs_ai_processing=EXCLUDED.needs_ai_processing,
        has_identified_name=EXCLUDED.has_identified_name, has_no_name=EXCLUDED.has_no_name,
        ai_status=EXCLUDED.ai_status, detalhes=EXCLUDED.detalhes, updated_at=now()
      RETURNING id
    ) SELECT count(*) INTO v_count FROM saved;

    DELETE FROM public.shopee_personalization_read_model rm
     WHERE rm.id = ANY(COALESCE(p_ids, ARRAY[]::integer[]))
       AND NOT EXISTS (SELECT 1 FROM public.view_vendas_personalizadas_v3 v WHERE v.id=rm.id);
    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.listar_pedidos_personalizados_projetados(
    p_page integer DEFAULT 1, p_page_size integer DEFAULT 20,
    p_search text DEFAULT '', p_ai_filter text DEFAULT '', p_chat_filter text DEFAULT '',
    p_integration_id integer DEFAULT NULL, p_include_unassigned boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_ready boolean; v_result jsonb;
BEGIN
  SELECT s.backfill_complete AND c.personalized_projection_enabled INTO v_ready
    FROM public.shopee_personalization_read_model_state s
    CROSS JOIN public.operational_read_model_config c
   WHERE s.singleton AND c.singleton;
  IF NOT COALESCE(v_ready,false) THEN RETURN jsonb_build_object('ready',false); END IF;
  WITH scoped AS MATERIALIZED (
    SELECT id,marketplace_integration_id,numero_pedido,numero_loja,nome_cliente,
           buyer_username,data_pedido,has_chat_messages,has_buyer_message,
           needs_ai_processing,has_identified_name,has_no_name
      FROM public.shopee_personalization_read_model r
     WHERE (p_integration_id IS NULL OR r.marketplace_integration_id=p_integration_id
            OR (p_include_unassigned AND r.marketplace_integration_id IS NULL))
  ), counts AS (
    SELECT count(*) FILTER (WHERE needs_ai_processing) pendente_ia,
           count(*) FILTER (WHERE has_chat_messages OR has_buyer_message) com_chat,
           count(*) FILTER (WHERE NOT (has_chat_messages OR has_buyer_message)) sem_chat,
           count(*) FILTER (WHERE has_identified_name) nome_identificado,
           count(*) FILTER (WHERE has_no_name) sem_nome FROM scoped
  ), filtered AS (
    SELECT r.* FROM scoped r
     WHERE (p_ai_filter <> 'pendente_ia' OR r.needs_ai_processing)
       AND (p_ai_filter <> 'nome_identificado' OR r.has_identified_name)
       AND (p_ai_filter <> 'sem_nome' OR r.has_no_name)
       AND (p_chat_filter <> 'com_chat' OR r.has_chat_messages)
       AND (p_chat_filter <> 'sem_chat' OR NOT r.has_chat_messages)
       AND (NULLIF(p_search,'') IS NULL OR r.numero_pedido ILIKE '%'||replace(p_search,'%',E'\\%')||'%' ESCAPE E'\\'
         OR r.numero_loja ILIKE '%'||replace(p_search,'%',E'\\%')||'%' ESCAPE E'\\'
         OR r.nome_cliente ILIKE '%'||replace(p_search,'%',E'\\%')||'%' ESCAPE E'\\'
         OR r.buyer_username ILIKE '%'||replace(p_search,'%',E'\\%')||'%' ESCAPE E'\\')
  ), page_rows AS (
    SELECT id,data_pedido FROM filtered ORDER BY data_pedido DESC, id DESC
      OFFSET (GREATEST(1,COALESCE(p_page,1))-1)*LEAST(100,GREATEST(1,COALESCE(p_page_size,20)))
      LIMIT LEAST(100,GREATEST(1,COALESCE(p_page_size,20)))
  )
  SELECT jsonb_build_object(
    'ready',true,
    'rows',COALESCE((SELECT jsonb_agg(r.detalhes ORDER BY page_rows.data_pedido DESC,page_rows.id DESC)
                       FROM page_rows JOIN public.shopee_personalization_read_model r USING(id)),'[]'::jsonb),
    'total',(SELECT count(*) FROM filtered),
    'status_counts',(SELECT to_jsonb(counts) FROM counts)
  ) INTO v_result;
  RETURN v_result;
END;
$$;

-- Keep the original resolver as a fallback for dates beyond the projected
-- horizon and while a new logistics group is being prepared.
CREATE OR REPLACE FUNCTION public.despacho_lote_proxima_saida_raw(
    p_modalidade_id integer, p_integration_id integer, p_data_limite date,
    p_tipo_prazo text, p_compromisso timestamptz, p_agora timestamptz DEFAULT now()
) RETURNS timestamptz LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
  SELECT CASE
    WHEN p_tipo_prazo='RELATIVO' THEN p_compromisso
    WHEN p_modalidade_id IS NULL OR p_data_limite IS NULL THEN NULL
    ELSE (SELECT min(janela.coleta_em)
            FROM generate_series(GREATEST(p_data_limite,(p_agora AT TIME ZONE 'America/Sao_Paulo')::date),
                                 GREATEST(p_data_limite,(p_agora AT TIME ZONE 'America/Sao_Paulo')::date)+31,interval '1 day') dias(dia)
            CROSS JOIN LATERAL public.janelas_logisticas(p_modalidade_id,p_integration_id,dias.dia::date) janela
           WHERE janela.coleta_em>p_agora)
  END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_lote_proxima_saida(
    p_modalidade_id integer, p_integration_id integer, p_data_limite date,
    p_tipo_prazo text, p_compromisso timestamptz, p_agora timestamptz DEFAULT now()
) RETURNS timestamptz LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO public, pg_temp AS $$
DECLARE v_inicio date; v_fim date;
BEGIN
  IF p_tipo_prazo='RELATIVO' THEN RETURN p_compromisso; END IF;
  IF p_modalidade_id IS NULL OR p_data_limite IS NULL THEN RETURN NULL; END IF;
  IF NOT (SELECT dispatch_windows_enabled FROM public.operational_read_model_config WHERE singleton) THEN
    RETURN public.despacho_lote_proxima_saida_raw(
        p_modalidade_id,p_integration_id,p_data_limite,p_tipo_prazo,p_compromisso,p_agora);
  END IF;
  v_inicio := GREATEST(p_data_limite,(p_agora AT TIME ZONE 'America/Sao_Paulo')::date);
  v_fim := v_inicio + 31;
  IF EXISTS (
      SELECT 1 FROM public.despacho_grupos_janelas_read_model g
       WHERE COALESCE(g.integration_id,-1)=COALESCE(p_integration_id,-1)
         AND g.modalidade_id=p_modalidade_id
         AND g.data_inicio <= v_inicio AND g.data_fim >= v_fim
  ) THEN
    RETURN (SELECT min(j.coleta_em) FROM public.despacho_janelas_read_model j
             WHERE COALESCE(j.integration_id,-1)=COALESCE(p_integration_id,-1)
               AND j.modalidade_id=p_modalidade_id AND j.dia BETWEEN v_inicio AND v_fim
               AND j.coleta_em>p_agora);
  END IF;
  RETURN public.despacho_lote_proxima_saida_raw(
      p_modalidade_id,p_integration_id,p_data_limite,p_tipo_prazo,p_compromisso,p_agora);
END;
$$;

CREATE OR REPLACE FUNCTION public.rebuild_despacho_janelas_read_model()
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_inicio date := (now() AT TIME ZONE 'America/Sao_Paulo')::date; v_grupos integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('rebuild_despacho_janelas_read_model'));
  DELETE FROM public.despacho_janelas_read_model;
  DELETE FROM public.despacho_grupos_janelas_read_model;
  INSERT INTO public.despacho_grupos_janelas_read_model(integration_id,modalidade_id,data_inicio,data_fim)
  SELECT DISTINCT p.marketplace_integration_id,p.modalidade_logistica_id,v_inicio,v_inicio+31
    FROM public.vw_pedidos_pendentes_despacho p
   WHERE p.modalidade_logistica_id IS NOT NULL;
  GET DIAGNOSTICS v_grupos = ROW_COUNT;
  INSERT INTO public.despacho_janelas_read_model(integration_id,modalidade_id,dia,coleta_em,payload)
  SELECT g.integration_id,g.modalidade_id,d.dia::date,j.coleta_em,to_jsonb(j)
    FROM public.despacho_grupos_janelas_read_model g
    CROSS JOIN generate_series(v_inicio,v_inicio+31,interval '1 day') d(dia)
    LEFT JOIN LATERAL public.janelas_logisticas(g.modalidade_id,g.integration_id,d.dia::date) j ON true;
  INSERT INTO public.despacho_janelas_read_model_state(singleton,data_inicio,data_fim,updated_at)
  VALUES(true,v_inicio,v_inicio+31,now())
  ON CONFLICT(singleton) DO UPDATE SET data_inicio=EXCLUDED.data_inicio,
      data_fim=EXCLUDED.data_fim,updated_at=EXCLUDED.updated_at;
  RETURN v_grupos;
END;
$$;

-- Shared context snapshot. Preserve despacho_arvore_contexto(date)'s contract;
-- the worker calls the raw function to rebuild it, while requests use this
-- wrapper and fall back to the raw query until a fresh snapshot exists.
CREATE OR REPLACE FUNCTION public.despacho_arvore_contexto_raw(p_data date)
RETURNS jsonb LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH arvore AS MATERIALIZED (SELECT * FROM public.despacho_arvore(p_data)),
integracoes AS (SELECT DISTINCT integration_id FROM arvore WHERE integration_id IS NOT NULL),
janelas AS (
 SELECT a.integration_id,a.modalidade_id,jsonb_agg(to_jsonb(j) ORDER BY j.coleta_em) dados
 FROM arvore a CROSS JOIN LATERAL public.janelas_logisticas(a.modalidade_id,a.integration_id,(a.coleta_em AT TIME ZONE 'America/Sao_Paulo')::date) j
 WHERE a.nivel=1 AND a.modalidade_id IS NOT NULL AND a.coleta_em IS NOT NULL GROUP BY a.integration_id,a.modalidade_id
)
SELECT jsonb_build_object(
 'rows',COALESCE((SELECT jsonb_agg(to_jsonb(a)) FROM arvore a),'[]'::jsonb),
 'timeline',COALESCE((SELECT jsonb_agg(to_jsonb(t)) FROM public.despacho_lotes_timeline(p_data) t),'[]'::jsonb),
 'catalogo',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',m.id,'entrega_rapida',m.entrega_rapida)) FROM public.modalidades_logisticas m),'[]'::jsonb),
 'integracoes',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',i.id,'module_id',i.module_id)) FROM public.installed_integrations i JOIN integracoes ids ON ids.integration_id=i.id),'[]'::jsonb),
 'composicao',COALESCE((SELECT jsonb_agg(to_jsonb(c)) FROM public.despacho_composicao_situacao(p_data)c),'[]'::jsonb),
 'lotes',COALESCE((SELECT jsonb_agg(to_jsonb(l)||jsonb_build_object('integration_id',ids.integration_id)) FROM integracoes ids CROSS JOIN LATERAL public.despacho_lotes(ids.integration_id)l),'[]'::jsonb),
 'rascunhos',COALESCE((SELECT jsonb_agg(to_jsonb(r)) FROM public.despacho_rascunhos_abertos(p_data)r),'[]'::jsonb),
 'janelas',COALESCE((SELECT jsonb_agg(to_jsonb(j)) FROM janelas j),'[]'::jsonb));
$$;

CREATE OR REPLACE FUNCTION public.refresh_operational_read_models(p_limit integer DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE e record; v_ids integer[] := ARRAY[]::integer[]; v_backfill integer := 0; v_dispatch boolean := false; v_dispatch_calendar boolean := false; v_processed integer := 0;
BEGIN
  IF NOT (SELECT backfill_complete FROM public.shopee_personalization_read_model_state WHERE singleton)
     AND NOT EXISTS (SELECT 1 FROM public.operational_read_model_outbox WHERE backfill) THEN
    INSERT INTO public.operational_read_model_outbox(event_key,personalized,backfill)
    SELECT 'order:'||p.id,true,true FROM public.pedidos p
    JOIN public.canais_venda cv ON cv.id=p.canal_venda_id AND cv.slug='shopee'
    WHERE p.situacao_pedido_id = 2
      AND EXISTS (SELECT 1 FROM public.itens_pedido ip WHERE ip.pedido_id=p.id AND ip.personalizado)
      AND NOT EXISTS (SELECT 1 FROM public.shopee_personalization_read_model r WHERE r.id=p.id)
    ORDER BY p.id LIMIT 100
    ON CONFLICT (event_key) DO UPDATE SET personalized=true,backfill=true;
  END IF;
  FOR e IN SELECT * FROM public.operational_read_model_outbox ORDER BY created_at LIMIT LEAST(500,GREATEST(1,p_limit)) FOR UPDATE SKIP LOCKED LOOP
    IF e.event_key LIKE 'order:%' THEN v_ids := array_append(v_ids, substring(e.event_key from 7)::integer);
    ELSIF e.event_key LIKE 'item:%' THEN
      v_ids := v_ids || ARRAY(SELECT pedido_id FROM public.itens_pedido WHERE id=substring(e.event_key from 6)::integer AND pedido_id IS NOT NULL);
    ELSIF e.event_key LIKE 'sn:%' THEN
      v_ids := v_ids || ARRAY(SELECT id FROM public.pedidos WHERE codigo_pedido_externo=substring(e.event_key from 4));
    ELSIF e.event_key LIKE 'user:%' THEN
      v_ids := v_ids || ARRAY(SELECT p.id FROM public.pedidos p JOIN public.canais_venda cv ON cv.id=p.canal_venda_id AND cv.slug='shopee' WHERE p.buyer_username=substring(e.event_key from 6) AND p.situacao_pedido_id IN (2,3,4));
    END IF;
    v_backfill := v_backfill + CASE WHEN e.backfill THEN 1 ELSE 0 END;
    v_dispatch := v_dispatch OR e.dispatch;
    v_dispatch_calendar := v_dispatch_calendar OR e.dispatch_calendar;
    DELETE FROM public.operational_read_model_outbox WHERE event_key=e.event_key;
    v_processed := v_processed + 1;
  END LOOP;
  IF cardinality(v_ids)>0 THEN PERFORM public.rebuild_shopee_personalization_read_model(ARRAY(SELECT DISTINCT unnest(v_ids))); END IF;
  IF NOT EXISTS (SELECT 1 FROM public.operational_read_model_outbox WHERE backfill) THEN
    IF NOT EXISTS (
       SELECT 1 FROM public.pedidos p JOIN public.canais_venda cv ON cv.id=p.canal_venda_id AND cv.slug='shopee'
       WHERE p.situacao_pedido_id = 2
         AND EXISTS (SELECT 1 FROM public.itens_pedido ip WHERE ip.pedido_id=p.id AND ip.personalizado)
         AND NOT EXISTS (SELECT 1 FROM public.shopee_personalization_read_model r WHERE r.id=p.id)
    ) THEN
      UPDATE public.shopee_personalization_read_model_state SET backfill_complete=true,updated_at=now() WHERE singleton;
    END IF;
  END IF;
  IF v_dispatch_calendar OR NOT EXISTS (
      SELECT 1 FROM public.despacho_janelas_read_model_state
       WHERE singleton AND data_inicio=(now() AT TIME ZONE 'America/Sao_Paulo')::date
         AND data_fim=(now() AT TIME ZONE 'America/Sao_Paulo')::date+31
  ) THEN
    PERFORM public.rebuild_despacho_janelas_read_model();
  ELSIF v_dispatch AND EXISTS (
      SELECT 1 FROM public.vw_pedidos_pendentes_despacho p
       WHERE p.modalidade_logistica_id IS NOT NULL
         AND NOT EXISTS (
           SELECT 1 FROM public.despacho_grupos_janelas_read_model g
            WHERE COALESCE(g.integration_id,-1)=COALESCE(p.marketplace_integration_id,-1)
              AND g.modalidade_id=p.modalidade_logistica_id
              AND g.data_inicio=(now() AT TIME ZONE 'America/Sao_Paulo')::date
              AND g.data_fim=(now() AT TIME ZONE 'America/Sao_Paulo')::date+31
         )
  ) THEN
    PERFORM public.rebuild_despacho_janelas_read_model();
  END IF;
  IF v_dispatch OR NOT EXISTS (SELECT 1 FROM public.despacho_contexto_read_model WHERE data=(now() AT TIME ZONE 'America/Sao_Paulo')::date AND valid_until>now()) THEN
    INSERT INTO public.despacho_contexto_read_model(data,payload,refreshed_at,valid_until)
    VALUES ((now() AT TIME ZONE 'America/Sao_Paulo')::date,public.despacho_arvore_contexto_raw((now() AT TIME ZONE 'America/Sao_Paulo')::date),now(),now()+interval '5 seconds')
    ON CONFLICT(data) DO UPDATE SET payload=EXCLUDED.payload,refreshed_at=EXCLUDED.refreshed_at,valid_until=EXCLUDED.valid_until;
  END IF;
  RETURN jsonb_build_object('processed',v_processed,'orders',cardinality(v_ids),'backfill_pending',(SELECT count(*) FROM public.operational_read_model_outbox WHERE backfill));
END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_arvore_contexto(p_data date)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_payload jsonb;
BEGIN
  IF NOT (SELECT dispatch_snapshot_enabled FROM public.operational_read_model_config WHERE singleton) THEN
    RETURN public.despacho_arvore_contexto_raw(p_data);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.operational_read_model_outbox WHERE dispatch) THEN
    SELECT payload INTO v_payload FROM public.despacho_contexto_read_model WHERE data=p_data AND valid_until>now();
  END IF;
  IF v_payload IS NOT NULL THEN RETURN v_payload; END IF;
  v_payload := public.despacho_arvore_contexto_raw(p_data);
  INSERT INTO public.despacho_contexto_read_model(data,payload,refreshed_at,valid_until)
  VALUES(p_data,v_payload,now(),now()+interval '5 seconds')
  ON CONFLICT(data) DO UPDATE SET payload=EXCLUDED.payload,
      refreshed_at=EXCLUDED.refreshed_at,valid_until=EXCLUDED.valid_until;
  RETURN v_payload;
END;
$$;

REVOKE ALL ON FUNCTION public.enqueue_operational_read_model_event(text,boolean,boolean,boolean,boolean),
 public.operational_read_model_source_trigger(), public.rebuild_shopee_personalization_read_model(integer[]),
 public.refresh_operational_read_models(integer), public.despacho_arvore_contexto_raw(date),
 public.despacho_lote_proxima_saida_raw(integer,integer,date,text,timestamptz,timestamptz),
 public.rebuild_despacho_janelas_read_model()
 FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.listar_pedidos_personalizados_projetados(integer,integer,text,text,text,integer,boolean)
 FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.listar_pedidos_personalizados_projetados(integer,integer,text,text,text,integer,boolean),
 public.refresh_operational_read_models(integer), public.despacho_arvore_contexto(date)
 TO service_role;

