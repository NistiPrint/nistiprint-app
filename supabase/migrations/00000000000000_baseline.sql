


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE SCHEMA IF NOT EXISTS "public";


ALTER SCHEMA "public" OWNER TO "pg_database_owner";


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE TYPE "public"."estagio_produto" AS ENUM (
    'RASCUNHO',
    'ARTE_PENDENTE',
    'ARTE_OK',
    'FICHA_OK',
    'CANAL_OK',
    'PUBLICADO',
    'DESCONTINUADO'
);


ALTER TYPE "public"."estagio_produto" OWNER TO "postgres";


CREATE TYPE "public"."integration_category" AS ENUM (
    'ERP',
    'Marketplace',
    'E-commerce',
    'Logistics',
    'Payment',
    'Other'
);


ALTER TYPE "public"."integration_category" OWNER TO "postgres";


CREATE TYPE "public"."tipo_produto_enum" AS ENUM (
    'MATERIA_PRIMA',
    'INTERMEDIARIO',
    'PRODUTO_ACABADO',
    'SERVICO'
);


ALTER TYPE "public"."tipo_produto_enum" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."accept_reliable_webhook_event"("p_source" "text", "p_dedupe_scope" "text", "p_dedupe_key" "text", "p_provider_event_id" "text", "p_payload_hash" "text", "p_raw_payload" "jsonb", "p_raw_body" "text", "p_received_at" timestamp with time zone, "p_correlation_id" "uuid", "p_resolved_order_id" "text" DEFAULT NULL::"text") RETURNS TABLE("webhook_event_id" bigint, "created" boolean, "should_process" boolean)
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
  accepted_id bigint;
BEGIN
  INSERT INTO public.webhook_events (
    source, dedupe_scope, dedupe_key, provider_event_id, payload_hash,
    raw_payload, raw_body, received_at, last_received_at, correlation_id,
    resolved_order_id, last_status, retry_expires_at
  ) VALUES (
    lower(trim(p_source)), COALESCE(NULLIF(p_dedupe_scope, ''), 'source'),
    p_dedupe_key, p_provider_event_id, p_payload_hash,
    COALESCE(p_raw_payload, '{}'::jsonb), p_raw_body,
    COALESCE(p_received_at, now()), COALESCE(p_received_at, now()),
    p_correlation_id, p_resolved_order_id, 'accepted', now() + interval '7 days'
  )
  ON CONFLICT (source, dedupe_scope, dedupe_key) DO NOTHING
  RETURNING id INTO accepted_id;

  IF accepted_id IS NOT NULL THEN
    RETURN QUERY SELECT accepted_id, true, true;
    RETURN;
  END IF;

  UPDATE public.webhook_events
  SET delivery_count = delivery_count + 1,
      last_received_at = GREATEST(
        COALESCE(last_received_at, received_at), COALESCE(p_received_at, now())
      )
  WHERE source = lower(trim(p_source))
    AND dedupe_scope = COALESCE(NULLIF(p_dedupe_scope, ''), 'source')
    AND dedupe_key = p_dedupe_key
  RETURNING id INTO accepted_id;

  RETURN QUERY SELECT accepted_id, false, false;
END;
$$;


ALTER FUNCTION "public"."accept_reliable_webhook_event"("p_source" "text", "p_dedupe_scope" "text", "p_dedupe_key" "text", "p_provider_event_id" "text", "p_payload_hash" "text", "p_raw_payload" "jsonb", "p_raw_body" "text", "p_received_at" timestamp with time zone, "p_correlation_id" "uuid", "p_resolved_order_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."apply_marketplace_order_event"("p_order" "jsonb", "p_snapshot" "jsonb" DEFAULT NULL::"jsonb", "p_refs" "jsonb" DEFAULT '[]'::"jsonb", "p_event" "jsonb" DEFAULT '{}'::"jsonb", "p_projection_enabled" boolean DEFAULT false) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    SET "search_path" TO ''
    AS $$
DECLARE
  v_module_id TEXT := lower(NULLIF(p_order->>'marketplace_module_id', ''));
  v_external_order_id TEXT := NULLIF(p_order->>'marketplace_order_id', '');
  v_existing_id BIGINT;
  v_pedido_id BIGINT;
  v_previous_status INTEGER;
  v_target_status INTEGER := NULLIF(p_event->>'target_situacao_pedido_id', '')::INTEGER;
  v_applied_status INTEGER;
  v_stage TEXT := COALESCE(NULLIF(p_event->>'lifecycle_stage', ''), 'unknown');
  v_provider_updated_at TIMESTAMPTZ := NULLIF(p_event->>'observed_at', '')::TIMESTAMPTZ;
  v_current_provider_updated_at TIMESTAMPTZ;
  v_decision TEXT := 'external_state_only';
  v_transition_id BIGINT;
BEGIN
  IF v_module_id IS NULL OR v_external_order_id IS NULL THEN
    RAISE EXCEPTION 'marketplace_module_id and marketplace_order_id are required';
  END IF;

  SELECT id, situacao_pedido_id INTO v_existing_id, v_previous_status
  FROM public.pedidos
  WHERE marketplace_module_id = v_module_id
    AND marketplace_order_id = v_external_order_id
  FOR UPDATE;

  v_pedido_id := public.upsert_canonical_order(
    p_order - 'situacao_pedido_id',
    p_snapshot,
    p_refs
  );

  SELECT situacao_pedido_id, marketplace_status_updated_at
  INTO v_previous_status, v_current_provider_updated_at
  FROM public.pedidos WHERE id = v_pedido_id FOR UPDATE;

  IF v_provider_updated_at IS NOT NULL
     AND v_current_provider_updated_at IS NOT NULL
     AND v_provider_updated_at < v_current_provider_updated_at THEN
    v_decision := 'ignored_stale';
  ELSE
    UPDATE public.pedidos SET
      marketplace_order_status = COALESCE(NULLIF(p_event->>'order_status', ''), marketplace_order_status),
      marketplace_payment_status = COALESCE(NULLIF(p_event->>'payment_status', ''), marketplace_payment_status),
      marketplace_shipping_status = COALESCE(NULLIF(p_event->>'shipping_status', ''), marketplace_shipping_status),
      marketplace_shipping_substatus = COALESCE(NULLIF(p_event->>'shipping_substatus', ''), marketplace_shipping_substatus),
      marketplace_lifecycle_stage = v_stage,
      marketplace_status_updated_at = COALESCE(v_provider_updated_at, marketplace_status_updated_at, now()),
      informacoes_cliente = CASE
        WHEN COALESCE(p_order->'informacoes_cliente', p_order->'customer', '{}'::jsonb) = '{}'::jsonb
          THEN informacoes_cliente
        ELSE COALESCE(p_order->'informacoes_cliente', p_order->'customer')
      END,
      updated_at = now()
    WHERE id = v_pedido_id;

    IF (v_existing_id IS NULL OR p_projection_enabled) AND v_target_status IS NOT NULL THEN
      v_applied_status := CASE
        WHEN v_target_status = 8 THEN 8
        WHEN v_previous_status = 8 THEN 8
        WHEN v_target_status = 7 AND v_previous_status IN (5, 6) THEN v_previous_status
        WHEN v_target_status = 7 THEN 7
        WHEN v_previous_status IN (6, 7) THEN v_previous_status
        WHEN v_target_status = 6 THEN 6
        WHEN v_target_status = 5 THEN 5
        WHEN v_target_status = 4 AND v_previous_status = 3 THEN 3
        WHEN v_target_status = 4 AND COALESCE(v_previous_status, 1) IN (1, 2, 4) THEN 4
        WHEN v_target_status = 2 AND COALESCE(v_previous_status, 1) IN (1, 2) THEN 2
        WHEN v_target_status = 1 AND COALESCE(v_previous_status, 1) = 1 THEN 1
        ELSE v_previous_status
      END;
      IF v_applied_status IS DISTINCT FROM v_previous_status THEN
        UPDATE public.pedidos
        SET situacao_pedido_id = v_applied_status, updated_at = now()
        WHERE id = v_pedido_id;
        v_decision := 'applied';
      ELSE
        v_decision := 'ignored_regression';
      END IF;
    ELSIF v_target_status IS NULL THEN
      v_decision := 'unmapped';
    END IF;
  END IF;

  SELECT situacao_pedido_id INTO v_applied_status
  FROM public.pedidos WHERE id = v_pedido_id;

  INSERT INTO public.marketplace_order_transitions (
    pedido_id, webhook_event_id, provider_event_id, module_id,
    external_order_id, lifecycle_stage, previous_situacao_pedido_id,
    requested_situacao_pedido_id, applied_situacao_pedido_id, decision,
    reason, provider_updated_at, provider_state
  ) VALUES (
    v_pedido_id, NULLIF(p_event->>'webhook_event_id', '')::BIGINT,
    NULLIF(p_event->>'provider_event_id', ''), v_module_id,
    v_external_order_id, v_stage, v_previous_status, v_target_status,
    v_applied_status, v_decision, p_event->>'reason',
    v_provider_updated_at, p_event
  )
  ON CONFLICT (module_id, provider_event_id, external_order_id)
    WHERE provider_event_id IS NOT NULL
  DO UPDATE SET webhook_event_id = COALESCE(
    EXCLUDED.webhook_event_id,
    public.marketplace_order_transitions.webhook_event_id
  )
  RETURNING id INTO v_transition_id;

  IF v_decision = 'applied' AND v_applied_status IN (7, 8) THEN
    INSERT INTO public.marketplace_order_effects (
      pedido_id, transition_id, effect_type, payload
    ) VALUES (
      v_pedido_id, v_transition_id, 'alert_active_demands',
      jsonb_build_object(
        'situacao_pedido_id', v_applied_status,
        'lifecycle_stage', v_stage,
        'external_order_id', v_external_order_id
      )
    )
    ON CONFLICT (transition_id, effect_type) DO NOTHING;
  END IF;

  RETURN jsonb_build_object(
    'pedido_id', v_pedido_id, 'transition_id', v_transition_id,
    'decision', v_decision,
    'previous_situacao_pedido_id', v_previous_status,
    'situacao_pedido_id', v_applied_status,
    'lifecycle_stage', v_stage
  );
END;
$$;


ALTER FUNCTION "public"."apply_marketplace_order_event"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb", "p_event" "jsonb", "p_projection_enabled" boolean) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."associar_canal_modalidade"("p_module_id" "text", "p_chave" "text", "p_modalidade_id" integer, "p_campo_origem" "text" DEFAULT NULL::"text") RETURNS TABLE("out_regra_id" integer, "out_pedidos_reclassificados" integer)
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_regra_id integer;
    v_campo    text;
    v_qtd      integer := 0;
    r          record;
BEGIN
    IF p_chave IS NULL OR btrim(p_chave) = '' THEN
        RAISE EXCEPTION 'chave do canal e obrigatoria' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT COALESCE(p_campo_origem, max(o.campo_origem)) INTO v_campo
      FROM public.metodos_envio_observados o
     WHERE o.module_id = p_module_id
       AND o.valor_normalizado = lower(btrim(p_chave));
    v_campo := COALESCE(v_campo, 'metodo_envio');

    -- Desassociar: modalidade nula desativa a regra e devolve os pedidos para
    -- "nao classificada". Nao apaga a regra, para o historico de quem associou
    -- o que continuar auditavel.
    IF p_modalidade_id IS NULL THEN
        UPDATE public.regras_classificacao_modalidade
           SET ativo = false, updated_at = now()
         WHERE module_id = p_module_id
           AND alvo = 'CHAVE'
           AND lower(valor) = lower(btrim(p_chave))
        RETURNING id INTO v_regra_id;
    ELSE
        SELECT id INTO v_regra_id
          FROM public.regras_classificacao_modalidade
         WHERE module_id = p_module_id
           AND alvo = 'CHAVE'
           AND lower(valor) = lower(btrim(p_chave))
         LIMIT 1;

        IF v_regra_id IS NULL THEN
            INSERT INTO public.regras_classificacao_modalidade (
                module_id, modalidade_id, campo_origem, alvo, operador, valor, prioridade
            ) VALUES (
                p_module_id, p_modalidade_id, v_campo, 'CHAVE', 'IGUAL', btrim(p_chave), 10
            ) RETURNING id INTO v_regra_id;
        ELSE
            UPDATE public.regras_classificacao_modalidade
               SET modalidade_id = p_modalidade_id, ativo = true, updated_at = now()
             WHERE id = v_regra_id;
        END IF;
    END IF;

    -- Reclassificacao retroativa dos pendentes que usam esse canal. So os
    -- pendentes: pedido ja despachado nao muda de lote por mudanca de cadastro.
    FOR r IN
        SELECT p.id FROM public.pedidos p
         WHERE p.marketplace_module_id = p_module_id
           AND lower(btrim(p.metodo_envio_chave)) = lower(btrim(p_chave))
           AND p.despachado_em IS NULL
           AND p.situacao_pedido_id IN (2, 3, 4)
    LOOP
        PERFORM public.classificar_pedido_modalidade(r.id);
        v_qtd := v_qtd + 1;
    END LOOP;

    IF p_modalidade_id IS NULL THEN
        UPDATE public.pedidos
           SET modalidade_logistica_id = NULL, modalidade_regra_id = NULL
         WHERE marketplace_module_id = p_module_id
           AND lower(btrim(metodo_envio_chave)) = lower(btrim(p_chave))
           AND despachado_em IS NULL
           AND situacao_pedido_id IN (2, 3, 4);
    END IF;

    RETURN QUERY SELECT v_regra_id, v_qtd;
END;
$$;


ALTER FUNCTION "public"."associar_canal_modalidade"("p_module_id" "text", "p_chave" "text", "p_modalidade_id" integer, "p_campo_origem" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."associar_canal_modalidade"("p_module_id" "text", "p_chave" "text", "p_modalidade_id" integer, "p_campo_origem" "text") IS 'Associa um canal de envio observado a uma modalidade e reclassifica os pedidos pendentes que o usam. Modalidade NULL desassocia sem apagar a regra.';



CREATE OR REPLACE FUNCTION "public"."atualizar_chave_combinacao_variacao"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
 UPDATE public.produtos p SET combinacao_chave=(SELECT string_agg(e.codigo||'='||o.codigo,'|' ORDER BY e.ordem_sku,e.id) FROM public.produto_variacao_valores vv JOIN public.produto_eixos e ON e.id=vv.eixo_id JOIN public.produto_eixo_opcoes o ON o.id=vv.opcao_id WHERE vv.produto_id=COALESCE(NEW.produto_id,OLD.produto_id)) WHERE p.id=COALESCE(NEW.produto_id,OLD.produto_id);
 RETURN COALESCE(NEW,OLD);
END $$;


ALTER FUNCTION "public"."atualizar_chave_combinacao_variacao"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."auditar_cadastro_produto"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE entidade text:=TG_TABLE_NAME; registro bigint;
BEGIN
 registro:=COALESCE((to_jsonb(NEW)->>'id')::bigint,(to_jsonb(OLD)->>'id')::bigint);
 INSERT INTO public.eventos_auditoria(tipo_evento,descricao,entidade_afetada,registro_id,dados_anteriores,dados_novos) VALUES (lower(TG_OP)||'_'||entidade,'Alteração no cadastro de produto/integracao',entidade,registro::integer,CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) ELSE NULL END,CASE WHEN TG_OP IN ('UPDATE','INSERT') THEN to_jsonb(NEW) ELSE NULL END);
 RETURN COALESCE(NEW,OLD);
END $$;


ALTER FUNCTION "public"."auditar_cadastro_produto"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."backfill_despachado_em"("p_limite" integer DEFAULT 5000) RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_total integer;
BEGIN
    WITH alvo AS (
        SELECT dp.pedido_id, min(d.created_at) AS despachado_em
          FROM public.demandas_pedidos dp
          JOIN public.demandas_producao d ON d.id = dp.demanda_id
          JOIN public.pedidos p ON p.id = dp.pedido_id
         WHERE p.despachado_em IS NULL
           AND COALESCE(d.status, '') <> 'RASCUNHO'
         GROUP BY dp.pedido_id
         LIMIT p_limite
    )
    UPDATE public.pedidos p
       SET despachado_em = alvo.despachado_em
      FROM alvo
     WHERE p.id = alvo.pedido_id;

    GET DIAGNOSTICS v_total = ROW_COUNT;
    RETURN v_total;
END;
$$;


ALTER FUNCTION "public"."backfill_despachado_em"("p_limite" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."backfill_despachado_em"("p_limite" integer) IS 'Rascunho nao despacha: demanda em RASCUNHO ainda recebe pedidos compativeis, entao seus pedidos continuam na arvore. Verificar o lexico de status vigente antes de rodar.';



CREATE OR REPLACE FUNCTION "public"."backfill_modalidade_pedidos"("p_limite" integer DEFAULT 1000) RETURNS TABLE("processados" integer, "classificados" integer)
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    r               record;
    v_processados   integer := 0;
    v_classificados integer := 0;
    v_modalidade_id integer;
BEGIN
    FOR r IN
        SELECT p.id,
               p.marketplace_integration_id,
               p.metodo_envio_chave,
               p.is_flex,
               p.marketplace_module_id AS module_id
          FROM public.pedidos p
         WHERE p.modalidade_logistica_id IS NULL
           AND p.modalidade_classificada_em IS NULL
         ORDER BY p.id DESC
         LIMIT p_limite
    LOOP
        v_processados := v_processados + 1;

        v_modalidade_id := public.classificar_pedido_modalidade(r.id);

        IF v_modalidade_id IS NULL AND r.is_flex AND r.module_id IS NOT NULL THEN
            SELECT m.id INTO v_modalidade_id
              FROM public.modalidades_logisticas m
             WHERE m.module_id = r.module_id
               AND m.codigo = 'FLEX'
               AND m.ativo;

            IF v_modalidade_id IS NOT NULL THEN
                UPDATE public.pedidos p
                   SET modalidade_logistica_id    = v_modalidade_id,
                       modalidade_classificada_em = now(),
                       compromisso_logistico_em   = public.resolver_compromisso_logistico(
                                                        v_modalidade_id,
                                                        r.marketplace_integration_id,
                                                        p.data_venda AT TIME ZONE 'America/Sao_Paulo',
                                                        now())
                 WHERE p.id = r.id;
            END IF;
        END IF;

        IF v_modalidade_id IS NOT NULL THEN
            v_classificados := v_classificados + 1;
        END IF;
    END LOOP;

    RETURN QUERY SELECT v_processados, v_classificados;
END;
$$;


ALTER FUNCTION "public"."backfill_modalidade_pedidos"("p_limite" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."backfill_modalidade_pedidos"("p_limite" integer) IS 'ORDER BY id DESC: o backlog aberto e recente e importa primeiro. Pedido que nao casar em nenhuma etapa fica com modalidade nula. Esse e o resultado correto, nao uma falha do backfill.';



CREATE OR REPLACE FUNCTION "public"."bom_efetiva_produto"("p_produto_id" integer) RETURNS TABLE("id" integer, "produto_pai_id" integer, "componente_id" integer, "quantidade_necessaria" numeric, "unidade_medida" character varying, "grupo" "text", "is_inherited" boolean)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public'
    AS $$
  WITH produto AS (
    SELECT p.id, p.sku, p.parent_id,
           (p.parent_id IS NOT NULL AND coalesce(p.herdar_bom_pai, false)) AS herda
      FROM public.produtos p WHERE p.id = p_produto_id
  ),
  proprio AS (
    SELECT f.*, public.grupo_bom_do_componente(f.componente_id, f.grupo) AS grupo_efetivo
      FROM public.ficha_tecnica f
      CROSS JOIN produto pr
     WHERE f.produto_pai_id = pr.id
        OR (f.produto_pai_id IS NULL AND f.sku_produto_pai IS NOT NULL
            AND f.sku_produto_pai = pr.sku)
  ),
  grupos_proprios AS (
    SELECT DISTINCT grupo_efetivo FROM proprio WHERE grupo_efetivo IS NOT NULL
  ),
  modo AS (
    SELECT pr.herda AS herda,
           (pr.herda AND EXISTS (SELECT 1 FROM grupos_proprios)) AS merge_por_grupo
      FROM produto pr
  ),
  pai AS (
    SELECT f.*, public.grupo_bom_do_componente(f.componente_id, f.grupo) AS grupo_efetivo
      FROM public.ficha_tecnica f
      CROSS JOIN produto pr
      CROSS JOIN modo m
     WHERE m.herda AND f.produto_pai_id = pr.parent_id
       AND (NOT m.merge_por_grupo
            OR NOT EXISTS (
                 SELECT 1 FROM grupos_proprios g
                  WHERE g.grupo_efetivo = public.grupo_bom_do_componente(f.componente_id, f.grupo)
               ))
  ),
  linhas AS (
    SELECT p.*, false AS herdada FROM proprio p
     CROSS JOIN modo m WHERE NOT m.herda OR m.merge_por_grupo
    UNION ALL
    SELECT p.*, true AS herdada FROM pai p
  )
  SELECT l.id, l.produto_pai_id, l.componente_id, l.quantidade_necessaria,
         l.unidade_medida, l.grupo_efetivo, l.herdada
    FROM linhas l WHERE l.componente_id IS NOT NULL ORDER BY l.id;
$$;


ALTER FUNCTION "public"."bom_efetiva_produto"("p_produto_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."bom_efetiva_produto"("p_produto_id" integer) IS 'Ficha tecnica efetiva. Sem grupo declarado o resultado e identico a regra legada (heranca ligada = ficha do pai; desligada = ficha propria). O merge por grupo so age quando ha linha propria com grupo.';



CREATE OR REPLACE FUNCTION "public"."bom_efetiva_produtos"("p_produto_ids" integer[]) RETURNS TABLE("produto_id" integer, "id" integer, "produto_pai_id" integer, "componente_id" integer, "quantidade_necessaria" numeric, "unidade_medida" character varying, "grupo" "text", "is_inherited" boolean)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public'
    AS $$
  SELECT alvo.id, b.id, b.produto_pai_id, b.componente_id,
         b.quantidade_necessaria, b.unidade_medida, b.grupo, b.is_inherited
    FROM unnest(coalesce(p_produto_ids, '{}'::integer[])) AS alvo(id)
    CROSS JOIN LATERAL public.bom_efetiva_produto(alvo.id) b
   ORDER BY alvo.id, b.id;
$$;


ALTER FUNCTION "public"."bom_efetiva_produtos"("p_produto_ids" integer[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."bom_efetiva_produtos"("p_produto_ids" integer[]) IS 'Versao em lote de bom_efetiva_produto. Mesma regra de heranca, uma chamada.';



CREATE OR REPLACE FUNCTION "public"."calcular_saldo_a_processar"("p_item_id" character varying, "p_produto_id" character varying, "p_quantidade_necessaria" numeric) RETURNS numeric
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_ja_alocado DECIMAL := 0;
BEGIN
    SELECT COALESCE(SUM(quantidade_alocada), 0)
    INTO v_ja_alocado
    FROM "public"."demanda_alocacoes_estoque"
    WHERE item_id = p_item_id
    AND produto_id = p_produto_id
    AND status != 'CANCELADA';

    RETURN GREATEST(p_quantidade_necessaria - v_ja_alocado, 0);
END;
$$;


ALTER FUNCTION "public"."calcular_saldo_a_processar"("p_item_id" character varying, "p_produto_id" character varying, "p_quantidade_necessaria" numeric) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."calcular_score_priorizacao_base"("p_modalidade_logistica" "text", "p_is_flex" boolean, "p_fulfillment" boolean, "p_classificacao_cliente" "text", "p_horario_coleta" time without time zone, "p_data_entrega" "date") RETURNS integer
    LANGUAGE "plpgsql" IMMUTABLE
    AS $$
DECLARE
    v_score integer := 0;
    v_hoje date := CURRENT_DATE;
    v_amanha date := CURRENT_DATE + INTERVAL '1 day';
BEGIN
    -- Score base por modalidade
    CASE p_modalidade_logistica
        WHEN 'EXPRESS' THEN v_score := v_score + 100;
        WHEN 'FULFILLMENT' THEN v_score := v_score + 75;
        WHEN 'STANDARD' THEN v_score := v_score + 25;
        WHEN 'RETIRADA' THEN v_score := v_score + 10;
    END CASE;
    
    -- Bônus FLEX
    IF p_is_flex THEN
        v_score := v_score + 50;
    END IF;
    
    -- Bônus Fulfillment
    IF p_fulfillment THEN
        v_score := v_score + 30;
    END IF;
    
    -- Bônus por classificação
    CASE p_classificacao_cliente
        WHEN 'B2B' THEN v_score := v_score + 20;
        WHEN 'INTERNO' THEN v_score := v_score + 5;
    END CASE;
    
    -- Bônus urgência temporal
    IF p_data_entrega = v_hoje THEN
        v_score := v_score + 80;
    ELSIF p_data_entrega = v_amanha THEN
        v_score := v_score + 40;
    END IF;
    
    -- Bônus horário de corte (quanto mais cedo, maior prioridade)
    IF p_horario_coleta IS NOT NULL THEN
        v_score := v_score + (24 - EXTRACT(HOUR FROM p_horario_coleta));
    END IF;
    
    RETURN v_score;
END;
$$;


ALTER FUNCTION "public"."calcular_score_priorizacao_base"("p_modalidade_logistica" "text", "p_is_flex" boolean, "p_fulfillment" boolean, "p_classificacao_cliente" "text", "p_horario_coleta" time without time zone, "p_data_entrega" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."calcular_score_priorizacao_base"("p_modalidade_logistica" "text", "p_is_flex" boolean, "p_fulfillment" boolean, "p_classificacao_cliente" "text", "p_horario_coleta" time without time zone, "p_data_entrega" "date") IS 'Calcula score base de priorização baseado em modalidade, urgência e horário';



CREATE OR REPLACE FUNCTION "public"."canais_envio_observados"("p_integration_id" integer DEFAULT NULL::integer) RETURNS TABLE("module_id" "text", "integration_id" integer, "campo_origem" "text", "chave" "text", "rotulo" "text", "ocorrencias" integer, "pedidos_pendentes" integer, "modalidade_id" integer, "modalidade_nome" "text", "regra_id" integer, "primeira_em" timestamp with time zone, "ultima_em" timestamp with time zone)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT
        o.module_id::text,
        p_integration_id,
        o.campo_origem::text,
        o.valor_bruto,
        o.rotulo_bruto,
        o.ocorrencias,
        COALESCE(pend.qtd, 0)::integer,
        r.modalidade_id,
        m.nome::text,
        r.id,
        o.primeira_ocorrencia_em,
        o.ultima_ocorrencia_em
      FROM public.metodos_envio_observados o
      -- A regra e por (module, alvo, valor): a associacao vale para todas as
      -- contas do mesmo marketplace, que e como o canal logistico funciona.
      LEFT JOIN public.regras_classificacao_modalidade r
             ON r.module_id = o.module_id
            AND r.alvo      = 'CHAVE'
            AND lower(r.valor) = o.valor_normalizado
            AND r.ativo
      LEFT JOIN public.modalidades_logisticas m ON m.id = r.modalidade_id
      LEFT JOIN LATERAL (
            SELECT count(*)::integer AS qtd
              FROM public.pedidos p
             WHERE p.metodo_envio_chave = o.valor_bruto
               AND p.marketplace_module_id = o.module_id
               AND p.despachado_em IS NULL
               AND p.situacao_pedido_id IN (2, 3, 4)
               AND (p_integration_id IS NULL
                    OR p.marketplace_integration_id = p_integration_id)
      ) pend ON true
     WHERE p_integration_id IS NULL
        OR o.module_id = (SELECT ii.module_id FROM public.installed_integrations ii
                           WHERE ii.id = p_integration_id)
     ORDER BY (r.modalidade_id IS NOT NULL), o.ocorrencias DESC;
$$;


ALTER FUNCTION "public"."canais_envio_observados"("p_integration_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."canais_envio_observados"("p_integration_id" integer) IS 'Canais de envio vistos no trafego real, com contagem e a modalidade associada. Nao associados primeiro: a tela existe para zerar essa fila.';



CREATE OR REPLACE FUNCTION "public"."cancelar_alocacao"("p_correlation_id" character varying, "p_motivo" "text" DEFAULT NULL::"text") RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    UPDATE "public"."demanda_alocacoes_estoque"
    SET status = 'CANCELADA',
        cancelled_at = NOW(),
        metadata = metadata || jsonb_build_object('motivo_cancelamento', p_motivo)
    WHERE correlation_id = p_correlation_id
    AND status != 'CANCELADA';
END;
$$;


ALTER FUNCTION "public"."cancelar_alocacao"("p_correlation_id" character varying, "p_motivo" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cascade_tipo_pai_para_variacoes"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  -- So cascateia se o registro alterado for um pai (sem parent_id)
  IF NEW.parent_id IS NOT NULL THEN
    RETURN NEW;
  END IF;

  IF NEW.tipo_produto IS DISTINCT FROM OLD.tipo_produto
     OR NEW.tipo_material IS DISTINCT FROM OLD.tipo_material THEN

    UPDATE public.produtos
       SET tipo_produto  = NEW.tipo_produto,
           tipo_material = NEW.tipo_material,
           updated_at    = CURRENT_TIMESTAMP
     WHERE parent_id = NEW.id
       AND (tipo_produto  IS DISTINCT FROM NEW.tipo_produto
         OR tipo_material IS DISTINCT FROM NEW.tipo_material);
  END IF;

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."cascade_tipo_pai_para_variacoes"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."cascade_tipo_pai_para_variacoes"() IS 'AFTER UPDATE em produtos: quando um pai (parent_id NULL) muda tipo_produto/tipo_material, cascateia o novo valor para todas as variacoes filhas.';



CREATE OR REPLACE FUNCTION "public"."categorizar_demanda_temporal"("p_data_entrega" "date", "p_horario_coleta" time without time zone) RETURNS "text"
    LANGUAGE "plpgsql" IMMUTABLE
    AS $$
DECLARE
    v_hoje date := CURRENT_DATE;
    v_amanha date := CURRENT_DATE + INTERVAL '1 day';
    v_horario_atual time := CURRENT_TIME;
BEGIN
    -- URGENTE: Entrega hoje com horário de corte nas próximas 4 horas
    IF p_data_entrega = v_hoje AND (p_horario_coleta - v_horario_atual) <= INTERVAL '4 hours' THEN
        RETURN 'URGENTE';
    END IF;
    
    -- HOJE: Entrega hoje
    IF p_data_entrega = v_hoje THEN
        RETURN 'HOJE';
    END IF;
    
    -- AMANHÃ: Entrega amanhã
    IF p_data_entrega = v_amanha THEN
        RETURN 'AMANHA';
    END IF;
    
    -- FUTURO: Entrega em data futura
    RETURN 'FUTURO';
END;
$$;


ALTER FUNCTION "public"."categorizar_demanda_temporal"("p_data_entrega" "date", "p_horario_coleta" time without time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."categorizar_demanda_temporal"("p_data_entrega" "date", "p_horario_coleta" time without time zone) IS 'Categoriza demanda temporalmente: URGENTE, HOJE, AMANHA, FUTURO';



CREATE OR REPLACE FUNCTION "public"."classificar_pedido_modalidade"("p_pedido_id" integer, "p_agora" timestamp with time zone DEFAULT "now"()) RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_integration_id integer;
    v_module_id      varchar(100);
    v_chave          text;
    v_rotulo         text;
    v_canonica       text;
    v_data_venda     timestamptz;
    v_regra_id       integer;
    v_modalidade_id  integer;
BEGIN
    SELECT p.marketplace_integration_id, p.marketplace_module_id,
           p.metodo_envio_chave, p.metodo_envio_rotulo, p.modalidade_logistica,
           p.data_venda AT TIME ZONE 'America/Sao_Paulo'
      INTO v_integration_id, v_module_id, v_chave, v_rotulo, v_canonica, v_data_venda
      FROM public.pedidos p WHERE p.id = p_pedido_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF v_module_id IS NOT NULL THEN
        SELECT r.id, r.modalidade_id
          INTO v_regra_id, v_modalidade_id
          FROM public.regras_classificacao_modalidade r
          JOIN public.modalidades_logisticas m ON m.id = r.modalidade_id AND m.ativo
         CROSS JOIN LATERAL (
            SELECT CASE r.alvo
                     WHEN 'ROTULO'   THEN v_rotulo
                     WHEN 'CANONICA' THEN v_canonica
                     ELSE v_chave
                   END AS alvo_valor
         ) a
         WHERE r.ativo
           AND r.module_id = v_module_id
           AND (r.integration_id IS NULL OR r.integration_id = v_integration_id)
           AND a.alvo_valor IS NOT NULL
           AND CASE r.operador
                 WHEN 'IGUAL' THEN
                     CASE WHEN r.case_sensitive THEN a.alvo_valor = r.valor
                          ELSE lower(a.alvo_valor) = lower(r.valor) END
                 WHEN 'CONTEM' THEN
                     CASE WHEN r.case_sensitive THEN position(r.valor in a.alvo_valor) > 0
                          ELSE position(lower(r.valor) in lower(a.alvo_valor)) > 0 END
                 WHEN 'PREFIXO' THEN
                     CASE WHEN r.case_sensitive THEN a.alvo_valor LIKE r.valor || '%'
                          ELSE lower(a.alvo_valor) LIKE lower(r.valor) || '%' END
                 WHEN 'REGEX' THEN
                     CASE WHEN r.case_sensitive THEN a.alvo_valor ~ r.valor
                          ELSE a.alvo_valor ~* r.valor END
                 ELSE false
               END
         ORDER BY (r.integration_id IS NULL), r.prioridade, r.id
         LIMIT 1;
    END IF;

    IF v_modalidade_id IS NULL THEN
        UPDATE public.pedidos SET modalidade_classificada_em = p_agora WHERE id = p_pedido_id;
        RETURN NULL;
    END IF;

    UPDATE public.pedidos
       SET modalidade_logistica_id    = v_modalidade_id,
           modalidade_regra_id        = v_regra_id,
           modalidade_classificada_em = p_agora,
           compromisso_logistico_em   = public.resolver_compromisso_logistico(
                                            v_modalidade_id, v_integration_id,
                                            v_data_venda, p_agora)
     WHERE id = p_pedido_id;

    UPDATE public.metodos_envio_observados
       SET status = 'CLASSIFICADO', modalidade_id = v_modalidade_id
     WHERE module_id = v_module_id
       AND valor_normalizado = lower(btrim(v_chave))
       AND status = 'NOVO';

    RETURN v_modalidade_id;
END;
$$;


ALTER FUNCTION "public"."classificar_pedido_modalidade"("p_pedido_id" integer, "p_agora" timestamp with time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."classificar_pedido_modalidade"("p_pedido_id" integer, "p_agora" timestamp with time zone) IS 'Tres alvos por prioridade: CHAVE (identificador estavel), ROTULO (nome do canal), CANONICA (pedidos.modalidade_logistica, ultimo recurso). Nao casar nada nunca apaga classificacao anterior.';



CREATE OR REPLACE FUNCTION "public"."cleanup_archived_ingest_hot_data"("p_limit" integer DEFAULT 1000) RETURNS TABLE("chat_deleted" integer, "events_deleted" integer)
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE deleted_chat integer := 0; deleted_events integer := 0;
BEGIN
  WITH candidates AS (
    SELECT message.id FROM public.mensagem_chat_shopee message
    WHERE message.raw_archived_at IS NOT NULL
      AND COALESCE(message.received_at, message.created_timestamp,
                   message.created_at AT TIME ZONE 'UTC') < now() - interval '30 days'
      AND NOT EXISTS (
        SELECT 1 FROM public.grupo_mensagens_chat_shopee bundle
        WHERE bundle.event_id = message.id
      )
    ORDER BY message.id LIMIT LEAST(GREATEST(COALESCE(p_limit, 1000), 1), 5000)
  )
  DELETE FROM public.mensagem_chat_shopee message
  USING candidates WHERE message.id = candidates.id;
  GET DIAGNOSTICS deleted_chat = ROW_COUNT;

  WITH candidates AS (
    SELECT id FROM public.webhook_events
    WHERE raw_archived_at IS NOT NULL
      AND received_at < now() - interval '30 days'
      AND last_status NOT IN ('pending', 'accepted', 'pending_retry', 'processing', 'manual_intervention')
    ORDER BY id LIMIT LEAST(GREATEST(COALESCE(p_limit, 1000), 1), 5000)
  )
  DELETE FROM public.webhook_events event
  USING candidates WHERE event.id = candidates.id;
  GET DIAGNOSTICS deleted_events = ROW_COUNT;
  RETURN QUERY SELECT deleted_chat, deleted_events;
END;
$$;


ALTER FUNCTION "public"."cleanup_archived_ingest_hot_data"("p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."coleta_do_pedido"("p_modalidade_id" integer, "p_integration_id" integer, "p_referencia" timestamp with time zone, "p_agora" timestamp with time zone DEFAULT "now"()) RETURNS TABLE("corte_em" timestamp with time zone, "coleta_em" timestamp with time zone, "prazo_final_em" timestamp with time zone)
    LANGUAGE "plpgsql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    c_tz    constant text := 'America/Sao_Paulo';
    v_tipo  text;
    v_corte time;
    v_dias  integer[];
    v_ref   timestamptz;
    v_dia   date;
    v_corte_dt timestamptz;
    v_primeira timestamptz;
    v_ultima   timestamptz;
    d       integer;
BEGIN
    IF p_modalidade_id IS NULL OR p_integration_id IS NULL THEN
        RETURN;
    END IF;

    SELECT ml.tipo_prazo INTO v_tipo
      FROM public.modalidades_logisticas ml WHERE ml.id = p_modalidade_id;

    -- RELATIVO nao tem coleta recorrente: cada pedido tem o proprio relogio.
    IF v_tipo IS DISTINCT FROM 'FIXO' THEN
        RETURN;
    END IF;

    -- Corte do lote e o mais cedo entre as regras que atendem esta modalidade.
    -- Duas saidas (coleta local e ponto de coleta) compartilham o mesmo corte:
    -- e um lote so, com duas chances de sair.
    SELECT min(r.horario_corte) INTO v_corte
      FROM public.regras_da_modalidade(p_modalidade_id, p_integration_id) r
     WHERE r.horario_corte IS NOT NULL;

    SELECT array_agg(DISTINCT dia) INTO v_dias
      FROM public.regras_da_modalidade(p_modalidade_id, p_integration_id) r2,
           LATERAL unnest(COALESCE(r2.dias_semana, ARRAY[1,2,3,4,5,6,7])) AS dia;

    IF v_corte IS NULL THEN
        RETURN;
    END IF;

    v_ref := COALESCE(p_referencia, p_agora);

    -- Comeca a busca no dia do pedido, nao no dia de hoje: o lote do pedido e
    -- definido por quando ele foi feito.
    FOR d IN 0..21 LOOP
        v_dia := (LEAST(v_ref, p_agora) AT TIME ZONE c_tz)::date + d;

        IF NOT (EXTRACT(isodow FROM v_dia)::integer = ANY (v_dias)) THEN
            CONTINUE;
        END IF;

        v_corte_dt := ((v_dia + v_corte) AT TIME ZONE c_tz);

        -- Corte anterior ao pedido nao podia inclui-lo.
        IF v_corte_dt < v_ref THEN
            CONTINUE;
        END IF;

        SELECT min(j.coleta_em), max(j.coleta_em)
          INTO v_primeira, v_ultima
          FROM public.janelas_logisticas(p_modalidade_id, p_integration_id, v_dia) j;

        IF v_primeira IS NULL THEN
            CONTINUE;
        END IF;

        -- Lote cuja ultima saida ja passou nao recebe mais nada: o pedido que
        -- ficou para tras entra no proximo. Ele continua atrasado perante o
        -- marketplace — isso os buckets de prazo mostram — mas o caminhao dele
        -- agora e outro.
        IF v_ultima <= p_agora THEN
            CONTINUE;
        END IF;

        corte_em       := v_corte_dt;
        coleta_em      := v_primeira;
        prazo_final_em := v_ultima;
        RETURN NEXT;
        RETURN;
    END LOOP;
END;
$$;


ALTER FUNCTION "public"."coleta_do_pedido"("p_modalidade_id" integer, "p_integration_id" integer, "p_referencia" timestamp with time zone, "p_agora" timestamp with time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."coleta_do_pedido"("p_modalidade_id" integer, "p_integration_id" integer, "p_referencia" timestamp with time zone, "p_agora" timestamp with time zone) IS 'Coleta a que um pedido pertence. O corte nao e prazo de producao: e a regra de pertencimento. Pedido feito ate o corte sai naquela coleta; feito depois, na proxima. Prazo de producao e a coleta — ou a ultima saida, quando o lote tem mais de uma.';



CREATE OR REPLACE FUNCTION "public"."consolidar_casar_refs"("p_refs" "text"[]) RETURNS TABLE("ref" "text", "pedido_id" integer, "numero_pedido" "text", "codigo_pedido_externo" "text", "marketplace_order_id" "text", "marketplace_integration_id" integer, "marketplace_nome" "text", "modalidade_logistica_id" integer, "modalidade_nome" "text", "data_limite_envio" timestamp with time zone, "situacao_pedido_id" integer, "despachado_em" timestamp with time zone, "na_torre" boolean)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
WITH refs AS (
    -- Deduplica preservando a grafia original: o operador procura no arquivo
    -- pelo que esta escrito nele, nao pela versao normalizada.
    SELECT DISTINCT
           btrim(r)            AS ref,
           upper(btrim(r))     AS chave
      FROM unnest(coalesce(p_refs, ARRAY[]::text[])) AS r
     WHERE btrim(coalesce(r, '')) <> ''
),
casado AS (
    SELECT r.ref,
           p.id,
           p.numero_pedido,
           p.codigo_pedido_externo,
           p.marketplace_order_id,
           p.marketplace_integration_id,
           p.modalidade_logistica_id,
           p.data_limite_envio,
           p.situacao_pedido_id,
           p.despachado_em,
           -- Empate e possivel quando dois pedidos compartilham o ID de origem
           -- (pacote). Fica com o mais recente: e o que o operador acabou de
           -- exportar do painel.
           row_number() OVER (PARTITION BY r.chave ORDER BY p.id DESC) AS posicao
      FROM refs r
      JOIN public.pedidos p
        ON upper(btrim(coalesce(p.marketplace_order_id, ''))) = r.chave
        OR upper(btrim(coalesce(p.codigo_pedido_externo, ''))) = r.chave
)
SELECT
    r.ref,
    c.id                                                        AS pedido_id,
    c.numero_pedido::text,
    c.codigo_pedido_externo::text,
    c.marketplace_order_id::text,
    c.marketplace_integration_id,
    coalesce(ii.instance_name, 'Origem nao resolvida')::text    AS marketplace_nome,
    c.modalidade_logistica_id,
    coalesce(m.nome, 'Modalidade não classificada')::text       AS modalidade_nome,
    c.data_limite_envio,
    c.situacao_pedido_id,
    c.despachado_em,
    -- na_torre responde a pergunta que decide o proximo clique: este pedido
    -- ainda pode entrar numa consolidacao? Um pedido ja despachado, cancelado
    -- ou preso a uma demanda publicada aparece casado (a base o tem) e fora da
    -- torre (nao entra em lote novo) — dizer so "encontrado" faria o operador
    -- procurar na torre por um pedido que nunca vai estar la.
    (v.id IS NOT NULL)                                          AS na_torre
  FROM refs r
  LEFT JOIN casado c
         ON c.ref = r.ref AND c.posicao = 1
  LEFT JOIN public.installed_integrations ii ON ii.id = c.marketplace_integration_id
  LEFT JOIN public.modalidades_logisticas  m ON m.id  = c.modalidade_logistica_id
  LEFT JOIN public.vw_pedidos_pendentes_despacho v ON v.id = c.id
 ORDER BY (c.id IS NULL) DESC, coalesce(ii.instance_name, ''), coalesce(m.nome, ''), r.ref;
$$;


ALTER FUNCTION "public"."consolidar_casar_refs"("p_refs" "text"[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."consolidar_casar_refs"("p_refs" "text"[]) IS 'Casa IDs de origem de uma planilha do marketplace com pedidos canonicos. Usada pela tela Consolidar para conferir o arquivo contra a base antes de consolidar o lote na Torre de Despacho.';



CREATE OR REPLACE FUNCTION "public"."contar_pedidos_novos_apos_edicao"("p_demanda_id" bigint) RETURNS integer
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE v_count INTEGER;
BEGIN SELECT COUNT(*) INTO v_count FROM public.demandas_pedidos dp WHERE dp.demanda_id = p_demanda_id AND dp.adicionado_apos_edicao = true; RETURN v_count; END;
$$;


ALTER FUNCTION "public"."contar_pedidos_novos_apos_edicao"("p_demanda_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."correct_canonical_order_identity"("p_pedido_id" bigint, "p_marketplace_module_id" "text", "p_marketplace_order_id" "text", "p_reason" "text", "p_actor_id" "text" DEFAULT NULL::"text") RETURNS bigint
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  v_old public.pedidos%ROWTYPE;
  v_module TEXT := lower(NULLIF(trim(p_marketplace_module_id), ''));
  v_order_id TEXT := NULLIF(trim(p_marketplace_order_id), '');
BEGIN
  IF v_module IS NULL OR v_order_id IS NULL OR NULLIF(trim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'New canonical identity and correction reason are required';
  END IF;

  SELECT * INTO v_old FROM public.pedidos WHERE id = p_pedido_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Pedido % not found', p_pedido_id;
  END IF;

  INSERT INTO public.order_identity_corrections (
    pedido_id, old_marketplace_module_id, old_marketplace_order_id,
    new_marketplace_module_id, new_marketplace_order_id, reason, actor_id
  ) VALUES (
    p_pedido_id, v_old.marketplace_module_id, v_old.marketplace_order_id,
    v_module, v_order_id, p_reason, p_actor_id
  );

  PERFORM set_config('app.allow_order_identity_correction', 'true', true);

  UPDATE public.pedidos
     SET marketplace_module_id = v_module,
         marketplace_order_id = v_order_id,
         codigo_pedido_externo = v_order_id,
         origem = upper(v_module),
         updated_at = now()
   WHERE id = p_pedido_id;

  UPDATE public.pedido_integration_refs
     SET module_id = v_module,
         external_order_id = v_order_id,
         updated_at = now()
   WHERE pedido_id = p_pedido_id AND role = 'sales_origin';

  RETURN p_pedido_id;
END;
$$;


ALTER FUNCTION "public"."correct_canonical_order_identity"("p_pedido_id" bigint, "p_marketplace_module_id" "text", "p_marketplace_order_id" "text", "p_reason" "text", "p_actor_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."demanda_atrasada"("p_demanda_id" integer, "p_agora" timestamp with time zone DEFAULT "now"()) RETURNS boolean
    LANGUAGE "sql" STABLE
    AS $$
    SELECT CASE
             WHEN d.status IN ('CONCLUIDO', 'Concluído', 'CANCELADO', 'Cancelado') THEN false
             WHEN d.escopo_despacho ->> 'prazo_final_em' IS NULL THEN false
             ELSE (d.escopo_despacho ->> 'prazo_final_em')::timestamptz < p_agora
           END
      FROM public.demandas_producao d
     WHERE d.id = p_demanda_id;
$$;


ALTER FUNCTION "public"."demanda_atrasada"("p_demanda_id" integer, "p_agora" timestamp with time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."demanda_atrasada"("p_demanda_id" integer, "p_agora" timestamp with time zone) IS 'Atraso e medido pela ULTIMA saida do lote, nao pela primeira. Uma demanda com coleta 17h e envio 19h que teve coleta parcial as 17h continua no prazo ate as 19h.';



CREATE OR REPLACE FUNCTION "public"."derivar_modalidade_logistica"("p_canal_venda_id" bigint, "p_servico_logistico" "text") RETURNS character varying
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE v_modalidade VARCHAR(50); v_padrao TEXT;
BEGIN
    FOR v_modalidade, v_padrao IN
        SELECT cmm.modalidade, cmm.padrao_servico FROM public.canal_modalidade_mapeamento cmm
        WHERE cmm.canal_venda_id = p_canal_venda_id AND cmm.ativo = true
        ORDER BY cmm.prioridade DESC, cmm.created_at DESC
    LOOP IF p_servico_logistico ILIKE v_padrao THEN RETURN v_modalidade; END IF; END LOOP;
    RETURN NULL;
END;
$$;


ALTER FUNCTION "public"."derivar_modalidade_logistica"("p_canal_venda_id" bigint, "p_servico_logistico" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."despacho_aba_do_bucket"("p_bucket" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    AS $$
    SELECT CASE p_bucket
             WHEN 'atrasado'  THEN 'hoje'
             WHEN 'hoje'      THEN 'hoje'
             WHEN 'sem_prazo' THEN 'hoje'
             WHEN 'amanha'    THEN 'amanha'
             ELSE 'proximos'
           END;
$$;


ALTER FUNCTION "public"."despacho_aba_do_bucket"("p_bucket" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_aba_do_bucket"("p_bucket" "text") IS 'Aba da torre a partir do bucket de prazo. sem_prazo cai em hoje de proposito: pedido sem prazo informado e tratado como a hipotese mais urgente, nao como o menos urgente. A aba nunca e uma contagem propria — e sempre derivada do mesmo bucket que a arvore usa.';



CREATE OR REPLACE FUNCTION "public"."despacho_arvore"("p_data" "date" DEFAULT CURRENT_DATE) RETURNS TABLE("nivel" smallint, "integration_id" integer, "marketplace_nome" "text", "modalidade_id" integer, "modalidade_codigo" "text", "modalidade_nome" "text", "tipo_prazo" "text", "bucket_prazo" "text", "coleta_grupo" timestamp with time zone, "qtd_pedidos" integer, "qtd_itens" integer, "corte_em" timestamp with time zone, "coleta_em" timestamp with time zone, "prazo_final_em" timestamp with time zone, "compromisso_mais_proximo" timestamp with time zone, "ordem" smallint)
    LANGUAGE "sql" STABLE
    AS $$
WITH base AS (
    SELECT
        p.id,
        p.marketplace_integration_id                    AS integration_id,
        p.marketplace_nome,
        p.modalidade_logistica_id                       AS modalidade_id,
        COALESCE(p.modalidade_codigo, 'NAO_CLASSIFICADA')          AS modalidade_codigo,
        COALESCE(p.modalidade_nome, 'Modalidade nao classificada') AS modalidade_nome,
        COALESCE(p.modalidade_tipo_prazo, 'FIXO')       AS tipo_prazo,
        COALESCE(p.modalidade_ordem, 0)::smallint       AS ordem,
        public.despacho_bucket_prazo(p.data_limite_envio, p_data)  AS bucket_prazo,
        p.compromisso_logistico_em,
        c.corte_em, c.coleta_em, c.prazo_final_em,
        COALESCE(i.qtd, 0)                              AS qtd_itens
      FROM public.vw_pedidos_pendentes_despacho p
      -- A coleta do pedido depende de QUANDO ele foi pago: o corte e regra de
      -- pertencimento, nao prazo de producao.
      LEFT JOIN LATERAL public.coleta_do_pedido(
                    p.modalidade_logistica_id, p.marketplace_integration_id,
                    COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda),
                    now()) c ON true
      LEFT JOIN LATERAL (
            SELECT round(sum(ip.quantidade))::integer AS qtd
              FROM public.itens_pedido ip WHERE ip.pedido_id = p.id) i ON true
)
SELECT
    CASE WHEN grouping(b.modalidade_id) = 1 THEN 0
         WHEN grouping(b.bucket_prazo) = 0  THEN 2
         WHEN grouping(b.coleta_em) = 0     THEN 3
         ELSE 1 END::smallint                                        AS nivel,
    b.integration_id,
    max(b.marketplace_nome)::text                                    AS marketplace_nome,
    CASE WHEN grouping(b.modalidade_id) = 0 THEN b.modalidade_id END AS modalidade_id,
    CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.modalidade_codigo)::text END,
    CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.modalidade_nome)::text END,
    CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.tipo_prazo)::text END,
    CASE WHEN grouping(b.bucket_prazo) = 0 THEN b.bucket_prazo END,
    CASE WHEN grouping(b.coleta_em) = 0    THEN b.coleta_em END,
    count(*)::integer, COALESCE(sum(b.qtd_itens), 0)::integer,
    min(b.corte_em), min(b.coleta_em), min(b.prazo_final_em),
    min(b.compromisso_logistico_em), COALESCE(min(b.ordem), 0)::smallint
  FROM base b
 GROUP BY GROUPING SETS (
    (b.integration_id),
    (b.integration_id, b.modalidade_id),
    (b.integration_id, b.modalidade_id, b.bucket_prazo),
    (b.integration_id, b.modalidade_id, b.coleta_em))
 ORDER BY
    CASE WHEN grouping(b.modalidade_id) = 1 THEN 0
         WHEN grouping(b.bucket_prazo) = 0  THEN 2
         WHEN grouping(b.coleta_em) = 0     THEN 3 ELSE 1 END,
    COALESCE(min(b.coleta_em), min(b.compromisso_logistico_em)) NULLS LAST,
    b.integration_id, COALESCE(min(b.ordem), 0),
    CASE WHEN grouping(b.bucket_prazo) = 1 THEN 0
         WHEN b.bucket_prazo = 'atrasado'  THEN 1
         WHEN b.bucket_prazo = 'hoje'      THEN 2
         WHEN b.bucket_prazo = 'amanha'    THEN 3
         WHEN b.bucket_prazo = 'depois'    THEN 4 ELSE 5 END;
$$;


ALTER FUNCTION "public"."despacho_arvore"("p_data" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_arvore"("p_data" "date") IS 'Quatro niveis: 0 marketplace, 1 modalidade, 2 quebra por prazo do marketplace, 3 quebra por coleta. Niveis 2 e 3 sao dois recortes do MESMO conjunto do nivel 1 — nao somar entre eles.';



CREATE OR REPLACE FUNCTION "public"."despacho_bucket_prazo"("p_data_limite" timestamp with time zone, "p_data" "date" DEFAULT CURRENT_DATE) RETURNS "text"
    LANGUAGE "sql" IMMUTABLE PARALLEL SAFE
    AS $$
    SELECT CASE
             WHEN p_data_limite IS NULL             THEN 'sem_prazo'
             WHEN p_data_limite::date <  p_data     THEN 'atrasado'
             WHEN p_data_limite::date =  p_data     THEN 'hoje'
             WHEN p_data_limite::date =  p_data + 1 THEN 'amanha'
             ELSE 'depois'
           END;
$$;


ALTER FUNCTION "public"."despacho_bucket_prazo"("p_data_limite" timestamp with time zone, "p_data" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_bucket_prazo"("p_data_limite" timestamp with time zone, "p_data" "date") IS 'Bucket de prazo de um pedido. Expressao unica e sem SET search_path pelo mesmo motivo que miolo_do_sku: precisa ser inlinavel. Nao acessa tabela.';



CREATE OR REPLACE FUNCTION "public"."despacho_cancelar_demanda"("p_demanda_id" integer, "p_motivo" "text" DEFAULT NULL::"text", "p_user_id" "text" DEFAULT 'System'::"text") RETURNS TABLE("out_demanda_codigo" "text", "out_pedidos_devolvidos" integer, "out_estornos_estoque" integer)
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_status  text;
    v_codigo  text;
    v_corr    uuid := gen_random_uuid();
    v_mov     record;
    v_antes   numeric;
    v_depois  numeric;
    v_estornos integer := 0;
    v_pedidos  integer := 0;
BEGIN
    SELECT d.status, d.demanda_id INTO v_status, v_codigo
      FROM public.demandas_producao d WHERE d.id = p_demanda_id FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE = 'no_data_found';
    END IF;

    IF v_status IN ('CANCELADO', 'Cancelado') THEN
        RAISE EXCEPTION 'Demanda % ja esta cancelada', v_codigo USING ERRCODE = 'invalid_parameter_value';
    END IF;

    -- Estorno das saidas de coleta. Producao (CONS_MP, PROD_INT, PROD_ACAB) NAO
    -- e estornada: o material foi consumido de verdade e o acabado existe na
    -- prateleira. So a saida — a mercadoria que nao saiu — volta.
    FOR v_mov IN
        SELECT m.id, m.produto_id, m.deposito_id, m.quantidade, m.item_demanda_id, m.produto_nome
          FROM public.movimentacoes_estoque m
          JOIN public.itens_demanda i ON i.id = m.item_demanda_id
         WHERE i.demanda_id = p_demanda_id
           AND m.tipo_movimentacao = 'SAIDA_COLETA'
           AND NOT EXISTS (
                 SELECT 1 FROM public.movimentacoes_estoque e
                  WHERE e.item_demanda_id = m.item_demanda_id
                    AND e.estagio = 'estorno_coleta'
                    AND e.produto_id = m.produto_id)
    LOOP
        SELECT saldo_atual INTO v_antes
          FROM public.estoque_atual
         WHERE produto_id = v_mov.produto_id AND deposito_id = v_mov.deposito_id
         FOR UPDATE;
        v_antes  := COALESCE(v_antes, 0);
        v_depois := v_antes - v_mov.quantidade;  -- quantidade da saida e negativa

        IF EXISTS (SELECT 1 FROM public.estoque_atual
                    WHERE produto_id = v_mov.produto_id AND deposito_id = v_mov.deposito_id) THEN
            UPDATE public.estoque_atual
               SET saldo_atual = v_depois, ultima_atualizacao = now(), updated_at = now()
             WHERE produto_id = v_mov.produto_id AND deposito_id = v_mov.deposito_id;
        ELSE
            INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_mov.produto_id, v_mov.deposito_id, v_depois, now());
        END IF;

        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, correlation_id,
            data_movimentacao, item_demanda_id, produto_nome, estagio
        ) VALUES (
            v_mov.produto_id, v_mov.deposito_id, 'ESTORNO', -v_mov.quantidade,
            v_antes, v_depois,
            'Estorno da coleta: demanda cancelada (mov. origem ' || v_mov.id || ')',
            v_corr, now(), v_mov.item_demanda_id, v_mov.produto_nome, 'estorno_coleta'
        );

        INSERT INTO public.demanda_estoque_processado (
            item_id, demanda_id, estagio, quantidade, correlation_id,
            saldo_acumulado, produto_id, tipo_movimentacao, created_at
        ) VALUES (
            v_mov.item_demanda_id, p_demanda_id, 'estorno_coleta', -v_mov.quantidade, v_corr,
            v_depois, v_mov.produto_id, 'ESTORNO', now()
        )
        ON CONFLICT DO NOTHING;

        v_estornos := v_estornos + 1;
    END LOOP;

    SELECT count(*) INTO v_pedidos
      FROM public.demandas_pedidos WHERE demanda_id = p_demanda_id;

    -- O trigger de sincronia limpa despachado_em a partir daqui.
    UPDATE public.demandas_producao
       SET status = 'CANCELADO',
           updated_at = now(),
           escopo_despacho = COALESCE(escopo_despacho, '{}'::jsonb) || jsonb_build_object(
               'cancelado_em', now(),
               'cancelado_por', p_user_id,
               'cancelamento_motivo', COALESCE(p_motivo, 'Nao informado'),
               'estorno_correlation_id', v_corr)
     WHERE id = p_demanda_id;

    INSERT INTO public.eventos_auditoria (tipo_evento, descricao, registro_id, dados_novos, created_at)
    VALUES ('DEMANDA_CANCELADA_COM_DEVOLUCAO',
            'Demanda cancelada; pedidos devolvidos a torre de despacho.',
            p_demanda_id,
            jsonb_build_object('demanda_id', p_demanda_id, 'demanda_codigo', v_codigo,
                               'status_anterior', v_status, 'pedidos_devolvidos', v_pedidos,
                               'estornos_estoque', v_estornos, 'motivo', p_motivo,
                               'usuario', p_user_id, 'correlation_id', v_corr),
            now());

    RETURN QUERY SELECT v_codigo, v_pedidos, v_estornos;
END;
$$;


ALTER FUNCTION "public"."despacho_cancelar_demanda"("p_demanda_id" integer, "p_motivo" "text", "p_user_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_cancelar_demanda"("p_demanda_id" integer, "p_motivo" "text", "p_user_id" "text") IS 'Cancela a demanda, estorna as saidas de coleta por movimento compensatorio e devolve os pedidos a torre (via trigger de sincronia). Producao nao e estornada: o material foi consumido de verdade.';



CREATE OR REPLACE FUNCTION "public"."despacho_composicao_situacao"("p_data" "date" DEFAULT CURRENT_DATE) RETURNS TABLE("integration_id" integer, "situacao_id" integer, "situacao_nome" "text", "qtd_pedidos" integer)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT p.marketplace_integration_id,
           p.situacao_pedido_id,
           sp.nome::text,
           count(*)::integer
      FROM public.vw_pedidos_pendentes_despacho p
      JOIN public.situacoes_pedido sp ON sp.id = p.situacao_pedido_id
     GROUP BY 1, 2, 3
     ORDER BY 1, 2;
$$;


ALTER FUNCTION "public"."despacho_composicao_situacao"("p_data" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_composicao_situacao"("p_data" "date") IS 'Composicao do total da torre por situacao interna. Existe para o card responder sozinho por que o total difere do filtro "Em Andamento" da tela de Pedidos: a torre inclui tambem Produzido e Pronto para Envio, que continuam sendo trabalho do galpao.';



CREATE OR REPLACE FUNCTION "public"."despacho_consolidar_pedidos"("p_pedido_ids" integer[]) RETURNS TABLE("ordem" integer, "miolo" "text", "miolo_chave" "text", "miolo_rank" integer, "miolo_total" numeric, "titulo_anuncio" "text", "sku_externo" "text", "variacao" "text", "quantidade" numeric, "produto_id" integer, "produto_nome" "text", "id_produto_miolo" integer, "miolo_origem" "text", "contabiliza_estoque" boolean, "pedidos_origem" integer[], "itens_origem" integer[])
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
),
base AS (
    SELECT ip.id AS item_id, ip.pedido_id,
           coalesce(nullif(btrim(ip.titulo_anuncio), ''),
                    nullif(btrim(ip.descricao), ''), '-')        AS titulo,
           coalesce(nullif(btrim(ip.sku_externo), ''), '-')      AS sku,
           coalesce(nullif(btrim(ip.variacao_externa), ''), '-') AS variacao,
           public.miolo_do_sku(ip.sku_externo)                   AS miolo_chave,
           ip.quantidade,
           ip.produto_id                                         AS produto_vinculado
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = ANY(p_pedido_ids)
),
resolvido AS (
    SELECT b.*, coalesce(b.produto_vinculado, pe.produto_id, pr.id) AS produto_final
      FROM base b
      LEFT JOIN LATERAL (
            SELECT x.produto_id FROM public.produtos_externos x
             WHERE b.produto_vinculado IS NULL
               AND upper(btrim(x.codigo_externo)) = upper(b.sku)
             ORDER BY CASE x.tipo WHEN 'SKU' THEN 1 WHEN 'ID' THEN 2 ELSE 3 END,
                      CASE WHEN x.plataforma IS NULL THEN 1 ELSE 0 END
             LIMIT 1
      ) pe ON true
      LEFT JOIN LATERAL (
            SELECT x.id FROM public.produtos x
             WHERE b.produto_vinculado IS NULL AND pe.produto_id IS NULL
               AND upper(btrim(x.sku)) = upper(b.sku)
             LIMIT 1
      ) pr ON true
),
kit_componentes AS (
    SELECT k.produto_id AS kit_id, c.*
      FROM (SELECT DISTINCT r.produto_final AS produto_id
              FROM resolvido r
              JOIN public.produtos p ON p.id = r.produto_final
             WHERE p.formato = 'kit') k
      CROSS JOIN LATERAL public.despacho_kit_componentes(k.produto_id) c
),
expandido AS (
    -- Tudo que nao e kit com ficha valida passa intacto: inclui item sem
    -- produto interno (produto_final NULL) e kit sem componente acabado.
    SELECT r.item_id, r.pedido_id, r.titulo, r.sku, r.variacao,
           r.miolo_chave, r.quantidade, r.produto_final, false AS de_kit
      FROM resolvido r
     WHERE NOT EXISTS (SELECT 1 FROM kit_componentes kc WHERE kc.kit_id = r.produto_final)
    UNION ALL
    -- Kit cadastrado: uma linha por produto acabado que o compoe. A linha do
    -- kit deixa de existir, e por isso o estoque nao e baixado duas vezes.
    SELECT r.item_id, r.pedido_id, kc.nome, kc.sku, '-',
           coalesce(kc.miolo_chave, r.miolo_chave),
           r.quantidade * coalesce(kc.quantidade, 1), kc.produto_id, true
      FROM resolvido r
      JOIN kit_componentes kc ON kc.kit_id = r.produto_final
),
com_bom AS (
    SELECT e.*, bom.componente_id AS miolo_produto_id, bom.componente_nome AS miolo_bom,
           p.nome AS produto_nome
      FROM expandido e
      CROSS JOIN cfg
      LEFT JOIN public.produtos p ON p.id = e.produto_final
      LEFT JOIN LATERAL (
            SELECT c.id AS componente_id, c.nome AS componente_nome
              FROM public.bom_efetiva_produto(e.produto_final) ft
              JOIN public.produtos c ON c.id = ft.componente_id
             WHERE c.categoria_id = cfg.cat_miolo
             ORDER BY ft.id LIMIT 1
      ) bom ON e.produto_final IS NOT NULL
),
ranks AS (
    SELECT miolo_chave, sum(quantidade) AS total,
           row_number() OVER (ORDER BY sum(quantidade) DESC, miolo_chave)::integer AS rank
      FROM com_bom GROUP BY miolo_chave
),
linhas AS (
    SELECT cb.titulo, cb.sku, cb.variacao, cb.miolo_chave,
           sum(cb.quantidade) AS qtd,
           max(cb.miolo_bom) AS miolo_bom, max(cb.miolo_produto_id) AS miolo_produto_id,
           max(cb.produto_final) AS produto_id, max(cb.produto_nome) AS produto_nome,
           array_agg(DISTINCT cb.pedido_id) AS pedidos,
           array_agg(DISTINCT cb.item_id) AS itens
      FROM com_bom cb
     GROUP BY cb.titulo, cb.sku, cb.variacao, cb.miolo_chave
)
SELECT (row_number() OVER (ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao, l.titulo))::integer,
       coalesce(l.miolo_bom, l.miolo_chave), l.miolo_chave, r.rank, r.total,
       l.titulo, l.sku, l.variacao, l.qtd, l.produto_id, l.produto_nome,
       l.miolo_produto_id,
       CASE WHEN l.miolo_bom IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
       (l.produto_id IS NOT NULL), l.pedidos, l.itens
  FROM linhas l JOIN ranks r ON r.miolo_chave = l.miolo_chave
 ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao, l.titulo;
$$;


ALTER FUNCTION "public"."despacho_consolidar_pedidos"("p_pedido_ids" integer[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_consolidar_pedidos"("p_pedido_ids" integer[]) IS 'Consolidacao canonica do lote. Kit cadastrado explode em seus produtos acabados; item sem produto interno resolvido continua virando linha (miolo pelo prefixo do SKU); kit sem ficha valida aparece como kit, para o operador ver a lacuna de cadastro.';



CREATE OR REPLACE FUNCTION "public"."despacho_escopo_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[] DEFAULT ARRAY['atrasado'::"text", 'hoje'::"text"], "p_data" "date" DEFAULT CURRENT_DATE) RETURNS SETOF integer
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT p.id
      FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (
             p.modalidade_logistica_id = ANY (p_modalidade_ids)
             -- NULL nao casa com ANY: o no "modalidade nao classificada" precisa
             -- ser alcancavel, senao ele aparece na torre e nao pode ser aberto.
             OR (p.modalidade_logistica_id IS NULL AND p_modalidade_ids IS NULL)
           )
       AND public.despacho_bucket_prazo(p.data_limite_envio, p_data) = ANY (p_horizonte)
     ORDER BY p.data_limite_envio NULLS LAST, p.id;
$$;


ALTER FUNCTION "public"."despacho_escopo_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_escopo_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date") IS 'Pedidos de um lote: um ou mais canais que compartilham a mesma janela. Passar NULL em p_modalidade_ids seleciona o no de modalidade nao classificada.';



CREATE OR REPLACE FUNCTION "public"."despacho_escopo_pedidos"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[] DEFAULT ARRAY['atrasado'::"text", 'hoje'::"text"], "p_data" "date" DEFAULT CURRENT_DATE) RETURNS SETOF integer
    LANGUAGE "sql" STABLE
    AS $$
    SELECT p.id
      FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id    IS NOT DISTINCT FROM p_modalidade_id
       AND public.despacho_bucket_prazo(p.data_limite_envio, p_data) = ANY (p_horizonte)
     ORDER BY p.data_limite_envio NULLS LAST, p.id;
$$;


ALTER FUNCTION "public"."despacho_escopo_pedidos"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_escopo_pedidos"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date") IS 'Predicado de pendencia identico ao de despacho_arvore, incluindo a exclusao de pedido ja em demanda publicada.';



CREATE OR REPLACE FUNCTION "public"."despacho_esteira_relativo"() RETURNS TABLE("pedido_id" integer, "numero_pedido" "text", "marketplace_nome" "text", "modalidade_id" integer, "modalidade_nome" "text", "modalidade_cor" "text", "nivel_interrupcao" smallint, "data_venda" timestamp with time zone, "compromisso_em" timestamp with time zone, "minutos_restantes" integer, "atrasado" boolean, "em_rascunho" boolean, "demanda_rascunho" "text")
    LANGUAGE "sql" STABLE
    AS $$
    SELECT
        p.id,
        p.numero_pedido::text,
        COALESCE(ii.instance_name, 'Origem nao resolvida')::text,
        m.id,
        m.nome::text,
        m.cor::text,
        m.nivel_interrupcao,
        (p.data_venda AT TIME ZONE 'America/Sao_Paulo'),
        p.compromisso_logistico_em,
        floor(EXTRACT(epoch FROM (p.compromisso_logistico_em - now())) / 60)::integer,
        (p.compromisso_logistico_em <= now()),
        (rascunho.demanda_id IS NOT NULL),
        rascunho.demanda_id::text
      FROM public.pedidos p
      JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
      LEFT JOIN public.installed_integrations ii ON ii.id = p.marketplace_integration_id
      LEFT JOIN LATERAL (
            SELECT d.demanda_id
              FROM public.demandas_pedidos dp
              JOIN public.demandas_producao d ON d.id = dp.demanda_id
             WHERE dp.pedido_id = p.id
               AND d.status = 'RASCUNHO'
             ORDER BY d.created_at DESC
             LIMIT 1
      ) rascunho ON true
     WHERE m.tipo_prazo = 'RELATIVO'
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND NOT EXISTS (
             SELECT 1
               FROM public.demandas_pedidos dp
               JOIN public.demandas_producao d ON d.id = dp.demanda_id
              WHERE dp.pedido_id = p.id
                AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
       )
     ORDER BY p.compromisso_logistico_em NULLS FIRST, p.id;
$$;


ALTER FUNCTION "public"."despacho_esteira_relativo"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_esteira_relativo"() IS 'Fila FIFO de prazo relativo. O pedido sai da fila quando entra em demanda publicada, nao quando recebe despachado_em: rascunho ainda nao e trabalho entregue ao atendimento.';



CREATE OR REPLACE FUNCTION "public"."despacho_excluir_demanda"("p_demanda_id" integer, "p_user_id" "text" DEFAULT 'System'::"text") RETURNS TABLE("out_demanda_codigo" "text", "out_pedidos_devolvidos" integer)
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_status   text;
    v_codigo   text;
    v_pedidos  integer;
    v_mov      integer;
    v_eventos  integer;
BEGIN
    SELECT d.status, d.demanda_id INTO v_status, v_codigo
      FROM public.demandas_producao d WHERE d.id = p_demanda_id FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE = 'no_data_found';
    END IF;

    -- Mensagem que nomeia o bloqueio, em vez do "violates foreign key
    -- constraint" que o operador nao consegue interpretar.
    SELECT count(*) INTO v_mov
      FROM public.movimentacoes_estoque m
      JOIN public.itens_demanda i ON i.id = m.item_demanda_id
     WHERE i.demanda_id = p_demanda_id;

    SELECT count(*) INTO v_eventos
      FROM public.demanda_estoque_processado WHERE demanda_id = p_demanda_id;

    IF v_mov > 0 OR v_eventos > 0 THEN
        RAISE EXCEPTION
          'Demanda % ja movimentou estoque (% movimentacoes, % registros de processamento) e nao pode ser excluida. Use o cancelamento, que estorna a coleta e devolve os pedidos a torre preservando o ledger.',
          v_codigo, v_mov, v_eventos
          USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT count(*) INTO v_pedidos
      FROM public.demandas_pedidos WHERE demanda_id = p_demanda_id;

    INSERT INTO public.eventos_auditoria (tipo_evento, descricao, registro_id, dados_novos, created_at)
    VALUES ('DEMANDA_EXCLUIDA',
            'Demanda excluida definitivamente; pedidos devolvidos a torre de despacho.',
            p_demanda_id,
            jsonb_build_object('demanda_id', p_demanda_id, 'demanda_codigo', v_codigo,
                               'status_anterior', v_status, 'pedidos_devolvidos', v_pedidos,
                               'usuario', p_user_id),
            now());

    -- CASCADE derruba itens_demanda e demandas_pedidos; o trigger de sincronia
    -- devolve os pedidos a torre.
    DELETE FROM public.demandas_producao WHERE id = p_demanda_id;

    RETURN QUERY SELECT v_codigo, v_pedidos;
END;
$$;


ALTER FUNCTION "public"."despacho_excluir_demanda"("p_demanda_id" integer, "p_user_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_excluir_demanda"("p_demanda_id" integer, "p_user_id" "text") IS 'Exclusao definitiva, permitida so para demanda sem rastro de estoque. Bloqueio devolve mensagem que nomeia o motivo e aponta o cancelamento. Pedidos voltam a torre pelo trigger de sincronia.';



CREATE OR REPLACE FUNCTION "public"."despacho_fechar_corte"("p_integration_id" integer, "p_modalidade_id" integer, "p_janela_em" timestamp with time zone, "p_user_id" "text" DEFAULT 'Sistema'::"text") RETURNS TABLE("out_demanda_id" integer, "out_demanda_codigo" "text", "out_qtd_pedidos" integer)
    LANGUAGE "plpgsql"
    AS $$
DECLARE v_qtd integer; v_execucao_id bigint;
BEGIN
    INSERT INTO public.janelas_despacho_execucoes (
        integration_id, modalidade_id, tipo, janela_em, qtd_pedidos, observacao)
    VALUES (p_integration_id, p_modalidade_id, 'CORTE', p_janela_em, 0, 'Registrando corte')
    ON CONFLICT (integration_id, modalidade_id, tipo, janela_em) DO NOTHING
    RETURNING id INTO v_execucao_id;

    IF v_execucao_id IS NULL THEN RETURN; END IF;

    -- Mesma fonte da arvore. Antes esta contagem tinha predicado proprio, que
    -- excluia pedido em rascunho — e por isso divergia da tela.
    SELECT count(*) INTO v_qtd
      FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id    IS NOT DISTINCT FROM p_modalidade_id
       AND COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda) <= p_janela_em;

    UPDATE public.janelas_despacho_execucoes
       SET qtd_pedidos = v_qtd,
           observacao  = format('Corte registrado com %s pedidos no lote. Demanda e criada pelo operador na Torre.', v_qtd)
     WHERE id = v_execucao_id;

    RETURN QUERY SELECT NULL::integer, NULL::text, v_qtd;
END;
$$;


ALTER FUNCTION "public"."despacho_fechar_corte"("p_integration_id" integer, "p_modalidade_id" integer, "p_janela_em" timestamp with time zone, "p_user_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_fechar_corte"("p_integration_id" integer, "p_modalidade_id" integer, "p_janela_em" timestamp with time zone, "p_user_id" "text") IS 'Registra que uma janela de corte venceu e quantos pedidos havia no lote. NAO cria demanda: rascunho nasce do clique do operador na Torre. Mantida porque a idempotencia da janela, o catch-up de janela perdida e o recalculo de compromisso pos-coleta dependem de janelas_despacho_execucoes.';



CREATE OR REPLACE FUNCTION "public"."despacho_kit_componentes"("p_produto_id" integer) RETURNS TABLE("produto_id" integer, "sku" "text", "nome" "text", "quantidade" numeric, "id_produto_miolo" integer, "miolo_nome" "text", "miolo_chave" "text")
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public'
    AS $$
  WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
  )
  SELECT c.id, c.sku::text, c.nome::text, ft.quantidade_necessaria,
         m.id, m.nome::text, public.miolo_do_sku(c.sku)
    FROM public.bom_efetiva_produto(p_produto_id) ft
    JOIN public.produtos c ON c.id = ft.componente_id
    CROSS JOIN cfg
    LEFT JOIN LATERAL (
      SELECT mc.id, mc.nome
        FROM public.bom_efetiva_produto(c.id) f2
        JOIN public.produtos mc ON mc.id = f2.componente_id
       WHERE mc.categoria_id = cfg.cat_miolo
       ORDER BY f2.id LIMIT 1
    ) m ON true
   WHERE c.tipo_produto = 'PRODUTO_ACABADO'
   ORDER BY c.id;
$$;


ALTER FUNCTION "public"."despacho_kit_componentes"("p_produto_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_kit_componentes"("p_produto_id" integer) IS 'Produtos acabados que compoem um kit, com o miolo de cada um. Alimenta a explosao de kit na previa.';



CREATE OR REPLACE FUNCTION "public"."despacho_lancar_escopo"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date", "p_nome" "text" DEFAULT NULL::"text", "p_user_id" "text" DEFAULT 'System'::"text", "p_observacoes" "text" DEFAULT NULL::"text") RETURNS TABLE("out_demanda_id" integer, "out_demanda_codigo" "text", "out_total_pedidos" integer, "out_total_itens" numeric, "out_complementar" boolean)
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_novos_ids         integer[];
    v_todos_ids         integer[];
    v_qtd_novos         integer;
    v_marketplace_nome  text;
    v_modalidade_nome   text;
    v_modalidade_codigo varchar(50);
    v_canal_venda_id    integer;
    v_demanda_pk        integer;
    v_demanda_codigo    text;
    v_janelas           jsonb;
    v_prazo_final       timestamptz;
    v_somou             boolean := false;
    v_total_itens       numeric := 0;
BEGIN
    SELECT array_agg(pedido_id) INTO v_novos_ids
      FROM public.despacho_escopo_pedidos(p_integration_id, p_modalidade_id, p_horizonte, p_data) AS pedido_id;

    v_qtd_novos := COALESCE(array_length(v_novos_ids, 1), 0);
    IF v_qtd_novos = 0 THEN
        RAISE EXCEPTION 'Escopo vazio: nenhum pedido em aberto para integration_id=%, modalidade_id=%, horizonte=%',
            p_integration_id, p_modalidade_id, p_horizonte
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT instance_name INTO v_marketplace_nome
      FROM public.installed_integrations WHERE id = p_integration_id;
    v_marketplace_nome := COALESCE(v_marketplace_nome, 'Origem nao resolvida');

    SELECT nome, codigo INTO v_modalidade_nome, v_modalidade_codigo
      FROM public.modalidades_logisticas WHERE id = p_modalidade_id;
    v_modalidade_nome := COALESCE(v_modalidade_nome, 'Modalidade nao classificada');

    SELECT p.canal_venda_id INTO v_canal_venda_id
      FROM public.pedidos p WHERE p.id = v_novos_ids[1];

    -- As saidas deste lote, congeladas na demanda. Antes so o fechamento
    -- automatico fazia isso; sem trazer para ca, uma demanda passaria a poder
    -- ser julgada atrasada por um horario que alguem editou na aba Logistica
    -- depois que o lote fechou.
    SELECT jsonb_agg(jsonb_build_object(
               'tipo_envio', j.tipo_envio, 'em', j.coleta_em,
               'ponto_coleta_id', j.ponto_coleta_id, 'ponto_nome', j.ponto_nome
           ) ORDER BY j.coleta_em),
           max(j.coleta_em)
      INTO v_janelas, v_prazo_final
      FROM public.janelas_logisticas(p_modalidade_id, p_integration_id, p_data) j;

    -- Rascunho aberto para o mesmo escopo recebe os pedidos em vez de virar um
    -- segundo lote para a mesma coleta.
    SELECT d.id, d.demanda_id INTO v_demanda_pk, v_demanda_codigo
      FROM public.demandas_producao d
     WHERE d.status = 'RASCUNHO'
       AND d.modalidade_id IS NOT DISTINCT FROM p_modalidade_id
       AND d.escopo_despacho ->> 'integration_id'  = p_integration_id::text
       AND d.escopo_despacho ->> 'data_operacional' = p_data::text
     ORDER BY d.created_at DESC
     LIMIT 1;

    IF v_demanda_pk IS NOT NULL THEN
        v_somou := true;
    ELSE
        v_demanda_codigo := format('DESPACHO-%s-%s-%s', p_integration_id,
            COALESCE(v_modalidade_codigo, 'SEMMOD'), to_char(p_data, 'YYYYMMDD'));

        INSERT INTO public.demandas_producao (
            demanda_id, descricao, status, tipo_demanda, canal_venda_id, data_entrega,
            observacoes, modalidade_id, modalidade_logistica, is_flex, escopo_despacho,
            origem_demanda, pedido_numero
        ) VALUES (
            v_demanda_codigo,
            COALESCE(p_nome, format('%s / %s - %s', v_marketplace_nome, v_modalidade_nome,
                                    to_char(p_data, 'DD/MM'))),
            'RASCUNHO', 'PLATAFORMA', v_canal_venda_id, p_data, p_observacoes,
            p_modalidade_id, v_modalidade_codigo, (v_modalidade_codigo = 'FLEX'),
            '{}'::jsonb, 'MANUAL', '0 pedidos'
        ) RETURNING id INTO v_demanda_pk;
    END IF;

    INSERT INTO public.demandas_pedidos (demanda_id, pedido_id)
    SELECT v_demanda_pk, unnest(v_novos_ids)
    ON CONFLICT (demanda_id, pedido_id) DO NOTHING;

    SELECT array_agg(dp.pedido_id ORDER BY dp.pedido_id) INTO v_todos_ids
      FROM public.demandas_pedidos dp WHERE dp.demanda_id = v_demanda_pk;

    -- A consolidacao e recalculada sobre o conjunto inteiro, nunca so sobre os
    -- pedidos novos: o rank do miolo depende da carga total do lote, entao somar
    -- linhas isoladamente daria uma ordem de producao errada.
    DELETE FROM public.demandas_item_origem
     WHERE demanda_item_id IN (SELECT id FROM public.itens_demanda WHERE demanda_id = v_demanda_pk);
    DELETE FROM public.itens_demanda WHERE demanda_id = v_demanda_pk;

    v_total_itens := public.despacho_materializar_itens(v_demanda_pk, v_todos_ids);

    UPDATE public.demandas_producao
       SET escopo_despacho = jsonb_build_object(
               'integration_id',  p_integration_id,
               'modalidade_id',   p_modalidade_id,
               'horizonte',       to_jsonb(p_horizonte),
               'data_operacional', p_data,
               'janelas',         COALESCE(v_janelas, '[]'::jsonb),
               'prazo_final_em',  v_prazo_final,
               'total_pedidos',   COALESCE(array_length(v_todos_ids, 1), 0),
               'montado_por',     p_user_id,
               'montado_em',      now()
           ),
           pedido_numero = COALESCE(array_length(v_todos_ids, 1), 0)::text || ' pedidos',
           updated_at    = now()
     WHERE id = v_demanda_pk;

    -- despachado_em NAO e carimbado aqui. Rascunho nao e despacho: o pedido
    -- continua na torre ate alguem publicar.
    RETURN QUERY SELECT v_demanda_pk, v_demanda_codigo,
                        COALESCE(array_length(v_todos_ids, 1), 0), v_total_itens, v_somou;
END;
$$;


ALTER FUNCTION "public"."despacho_lancar_escopo"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_lancar_escopo"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") IS 'Monta um rascunho de demanda a partir de um no da torre. Nao publica e nao carimba despachado_em — o pedido continua na torre ate a publicacao. Lancar de novo no mesmo escopo soma no rascunho aberto e recalcula a consolidacao sobre o lote inteiro. out_complementar indica que somou em vez de criar.';



CREATE OR REPLACE FUNCTION "public"."despacho_lancar_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date", "p_nome" "text" DEFAULT NULL::"text", "p_user_id" "text" DEFAULT 'System'::"text", "p_observacoes" "text" DEFAULT NULL::"text") RETURNS TABLE("out_demanda_id" integer, "out_demanda_codigo" "text", "out_total_pedidos" integer, "out_total_itens" numeric, "out_complementar" boolean)
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_novos_ids         integer[];
    v_todos_ids         integer[];
    v_qtd_novos         integer;
    v_marketplace_nome  text;
    v_modalidade_princ  integer;
    v_codigo_princ      varchar(50);
    v_nomes             text;
    v_canal_venda_id    integer;
    v_demanda_pk        integer;
    v_demanda_codigo    text;
    v_janelas           jsonb;
    v_prazo_final       timestamptz;
    v_somou             boolean := false;
    v_total_itens       numeric := 0;
    v_chave             text;
BEGIN
    SELECT array_agg(pedido_id) INTO v_novos_ids
      FROM public.despacho_escopo_lote(p_integration_id, p_modalidade_ids, p_horizonte, p_data) AS pedido_id;

    v_qtd_novos := COALESCE(array_length(v_novos_ids, 1), 0);
    IF v_qtd_novos = 0 THEN
        RAISE EXCEPTION 'Escopo vazio: nenhum pedido em aberto para integration_id=%, modalidades=%, horizonte=%',
            p_integration_id, p_modalidade_ids, p_horizonte USING ERRCODE = 'no_data_found';
    END IF;

    SELECT instance_name INTO v_marketplace_nome
      FROM public.installed_integrations WHERE id = p_integration_id;
    v_marketplace_nome := COALESCE(btrim(v_marketplace_nome), 'Origem nao resolvida');

    -- A modalidade principal do lote e a de menor ordem de exibicao: e ela que
    -- da o codigo da demanda, para o codigo continuar estavel quando um canal
    -- secundario for adicionado ou removido do lote.
    SELECT m.id, m.codigo, string_agg(m2.nome, ' + ' ORDER BY m2.ordem_exibicao, m2.nome)
      INTO v_modalidade_princ, v_codigo_princ, v_nomes
      FROM public.modalidades_logisticas m
      JOIN public.modalidades_logisticas m2 ON m2.id = ANY (p_modalidade_ids)
     WHERE m.id = ANY (p_modalidade_ids)
     GROUP BY m.id, m.codigo, m.ordem_exibicao
     ORDER BY m.ordem_exibicao, m.id
     LIMIT 1;

    v_nomes := COALESCE(v_nomes, 'Modalidade nao classificada');
    SELECT p.canal_venda_id INTO v_canal_venda_id
      FROM public.pedidos p WHERE p.id = v_novos_ids[1];

    -- As saidas deste lote, congeladas na demanda: um lote fechado hoje nao pode
    -- ser julgado atrasado por um horario que alguem editou amanha.
    SELECT jsonb_agg(jsonb_build_object(
               'tipo_envio', j.tipo_envio, 'em', j.coleta_em,
               'ponto_coleta_id', j.ponto_coleta_id, 'ponto_nome', j.ponto_nome
           ) ORDER BY j.coleta_em), max(j.coleta_em)
      INTO v_janelas, v_prazo_final
      FROM public.janelas_logisticas(v_modalidade_princ, p_integration_id, p_data) j;

    -- Chave do rascunho aberto: o lote, nao a modalidade.
    v_chave := p_integration_id::text || ':' ||
               COALESCE(array_to_string(ARRAY(SELECT unnest(p_modalidade_ids) ORDER BY 1), ','), 'nc');

    SELECT d.id, d.demanda_id INTO v_demanda_pk, v_demanda_codigo
      FROM public.demandas_producao d
     WHERE d.status = 'RASCUNHO'
       AND d.escopo_despacho ->> 'lote_chave' = v_chave
       AND d.escopo_despacho ->> 'data_operacional' = p_data::text
     ORDER BY d.created_at DESC LIMIT 1;

    IF v_demanda_pk IS NOT NULL THEN
        v_somou := true;
    ELSE
        v_demanda_codigo := format('DESPACHO-%s-%s-%s', p_integration_id,
            COALESCE(v_codigo_princ, 'SEMMOD'), to_char(p_data, 'YYYYMMDD'));

        INSERT INTO public.demandas_producao (
            demanda_id, descricao, status, tipo_demanda, canal_venda_id, data_entrega,
            observacoes, modalidade_id, modalidade_logistica, is_flex, escopo_despacho,
            origem_demanda, pedido_numero
        ) VALUES (
            v_demanda_codigo,
            COALESCE(p_nome, format('%s / %s - %s', v_marketplace_nome, v_nomes, to_char(p_data, 'DD/MM'))),
            'RASCUNHO', 'PLATAFORMA', v_canal_venda_id, p_data, p_observacoes,
            v_modalidade_princ, v_codigo_princ, (v_codigo_princ = 'FLEX'),
            '{}'::jsonb, 'MANUAL', '0 pedidos'
        ) RETURNING id INTO v_demanda_pk;
    END IF;

    INSERT INTO public.demandas_pedidos (demanda_id, pedido_id)
    SELECT v_demanda_pk, unnest(v_novos_ids)
    ON CONFLICT (demanda_id, pedido_id) DO NOTHING;

    SELECT array_agg(dp.pedido_id ORDER BY dp.pedido_id) INTO v_todos_ids
      FROM public.demandas_pedidos dp WHERE dp.demanda_id = v_demanda_pk;

    -- Recalcula sobre o conjunto inteiro: o rank do miolo depende da carga total
    -- do lote, entao somar linhas isoladamente daria uma ordem de producao errada.
    DELETE FROM public.demandas_item_origem
     WHERE demanda_item_id IN (SELECT id FROM public.itens_demanda WHERE demanda_id = v_demanda_pk);
    DELETE FROM public.itens_demanda WHERE demanda_id = v_demanda_pk;

    v_total_itens := public.despacho_materializar_itens(v_demanda_pk, v_todos_ids);

    UPDATE public.demandas_producao
       SET escopo_despacho = jsonb_build_object(
               'integration_id',   p_integration_id,
               'lote_chave',       v_chave,
               'modalidade_ids',   to_jsonb(p_modalidade_ids),
               'modalidade_id',    v_modalidade_princ,
               'horizonte',        to_jsonb(p_horizonte),
               'data_operacional', p_data,
               'janelas',          COALESCE(v_janelas, '[]'::jsonb),
               'prazo_final_em',   v_prazo_final,
               'total_pedidos',    COALESCE(array_length(v_todos_ids, 1), 0),
               'montado_por',      p_user_id,
               'montado_em',       now()
           ),
           pedido_numero = COALESCE(array_length(v_todos_ids, 1), 0)::text || ' pedidos',
           updated_at    = now()
     WHERE id = v_demanda_pk;

    -- despachado_em NAO e carimbado aqui: rascunho nao e despacho.
    RETURN QUERY SELECT v_demanda_pk, v_demanda_codigo,
                        COALESCE(array_length(v_todos_ids, 1), 0), v_total_itens, v_somou;
END;
$$;


ALTER FUNCTION "public"."despacho_lancar_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_lancar_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") IS 'Monta o rascunho de um lote (um ou mais canais que compartilham a janela). Nao publica e nao carimba despachado_em. Lancar de novo no mesmo lote soma no rascunho aberto e recalcula a consolidacao sobre o conjunto inteiro.';



CREATE OR REPLACE FUNCTION "public"."despacho_lancar_pedidos"("p_pedido_ids" integer[], "p_nome" "text" DEFAULT NULL::"text", "p_user_id" "text" DEFAULT 'System'::"text", "p_observacoes" "text" DEFAULT NULL::"text", "p_escopo" "jsonb" DEFAULT '{}'::"jsonb") RETURNS TABLE("out_demanda_id" integer, "out_demanda_codigo" "text", "out_total_pedidos" integer, "out_total_itens" numeric, "out_complementar" boolean, "out_ja_em_rascunho" "jsonb")
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_ids            integer[];
    v_todos_ids      integer[];
    v_conflitos      jsonb;
    v_conferencia    text := NULLIF(p_escopo ->> 'conferencia_id', '');
    v_demanda        integer;
    v_codigo         text;
    v_integration_id integer;
    v_modalidade_id  integer;
    v_codigo_mod     varchar(50);
    v_canal_id       integer;
    v_marketplace    text;
    v_nos            jsonb;
    v_somou          boolean := false;
    v_total_itens    numeric := 0;
BEGIN
    -- 1. Do que o chamador pediu, o que ainda esta pendente de despacho.
    SELECT array_agg(DISTINCT p.id ORDER BY p.id) INTO v_ids
      FROM public.pedidos p
     WHERE p.id = ANY(COALESCE(p_pedido_ids, '{}'::integer[]))
       AND p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4);

    -- 2. O rascunho desta conferencia, se ja existir. Relancar a mesma planilha
    --    SOMA nele; nao cria um segundo lote para o mesmo recorte.
    IF v_conferencia IS NOT NULL THEN
        SELECT d.id INTO v_demanda
          FROM public.demandas_producao d
         WHERE d.status = 'RASCUNHO'
           AND d.escopo_despacho ->> 'conferencia_id' = v_conferencia
         ORDER BY d.id DESC LIMIT 1;
        v_somou := v_demanda IS NOT NULL;
    END IF;

    -- 3. Guarda: um pedido nao pode estar em dois rascunhos abertos. O proprio
    --    rascunho desta conferencia nao conta como conflito — senao relancar
    --    seria recusado pelo lote que ele mesmo criou.
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'pedido_id',      dp.pedido_id,
                'demanda_id',     dp.demanda_id,
                'demanda_codigo', d.demanda_id,
                'descricao',      d.descricao
           ) ORDER BY dp.pedido_id), '[]'::jsonb)
      INTO v_conflitos
      FROM public.demandas_pedidos dp
      JOIN public.demandas_producao d ON d.id = dp.demanda_id
     WHERE dp.pedido_id = ANY(COALESCE(v_ids, '{}'::integer[]))
       AND d.status = 'RASCUNHO'
       AND (v_demanda IS NULL OR dp.demanda_id <> v_demanda);

    SELECT array_agg(x.pedido_id ORDER BY x.pedido_id) INTO v_ids
      FROM (
        SELECT unnest(COALESCE(v_ids, '{}'::integer[])) AS pedido_id
        EXCEPT
        SELECT (item ->> 'pedido_id')::integer
          FROM jsonb_array_elements(v_conflitos) item
      ) x;

    IF COALESCE(array_length(v_ids, 1), 0) = 0 AND NOT v_somou THEN
        RAISE EXCEPTION 'Escopo vazio: nenhum pedido disponivel para lancamento'
            USING ERRCODE = 'no_data_found', DETAIL = v_conflitos::text;
    END IF;

    -- 4. Contexto do lote, derivado do conjunto real. O arquivo pode atravessar
    --    mais de um no da torre; o lote e nomeado pelo majoritario e guarda a
    --    composicao inteira em escopo_despacho.nos para a tela poder avisar.
    SELECT t.marketplace_integration_id, t.modalidade_logistica_id, t.canal_venda_id
      INTO v_integration_id, v_modalidade_id, v_canal_id
      FROM (
        SELECT p.marketplace_integration_id, p.modalidade_logistica_id,
               p.canal_venda_id, count(*) AS qtd
          FROM public.pedidos p
         WHERE p.id = ANY(COALESCE(v_ids, '{}'::integer[]))
            OR p.id IN (SELECT dp.pedido_id FROM public.demandas_pedidos dp
                         WHERE dp.demanda_id = v_demanda)
         GROUP BY 1, 2, 3
      ) t
     ORDER BY t.qtd DESC, t.marketplace_integration_id NULLS LAST
     LIMIT 1;

    SELECT m.codigo INTO v_codigo_mod
      FROM public.modalidades_logisticas m WHERE m.id = v_modalidade_id;

    SELECT COALESCE(btrim(ii.instance_name), 'Origem nao resolvida') INTO v_marketplace
      FROM public.installed_integrations ii WHERE ii.id = v_integration_id;
    v_marketplace := COALESCE(v_marketplace, 'Origem nao resolvida');

    -- 5. Cria o rascunho, ou reaproveita o desta conferencia.
    IF v_demanda IS NULL THEN
        v_codigo := COALESCE(
            NULLIF(p_escopo ->> 'codigo', ''),
            CASE WHEN v_conferencia IS NOT NULL
                 THEN 'DESPACHO-ARQ-' || v_conferencia
                 ELSE 'DESPACHO-SEL-' || to_char(now(), 'YYYYMMDDHH24MISS')
            END);

        INSERT INTO public.demandas_producao (
            demanda_id, descricao, status, tipo_demanda, canal_venda_id,
            data_entrega, observacoes, modalidade_id, modalidade_logistica,
            is_flex, escopo_despacho, origem_demanda, pedido_numero
        ) VALUES (
            v_codigo,
            COALESCE(
                NULLIF(p_nome, ''),
                NULLIF(p_escopo ->> 'nome', ''),
                format('%s / %s - %s', v_marketplace,
                       COALESCE(NULLIF(p_escopo ->> 'arquivo_nome', ''), 'Selecao'),
                       to_char(CURRENT_DATE, 'DD/MM'))),
            'RASCUNHO', 'PLATAFORMA', v_canal_id, CURRENT_DATE, p_observacoes,
            v_modalidade_id, v_codigo_mod, (v_codigo_mod = 'FLEX'),
            '{}'::jsonb, 'MANUAL', '0 pedidos'
        ) RETURNING id INTO v_demanda;
    END IF;

    INSERT INTO public.demandas_pedidos (demanda_id, pedido_id)
    SELECT v_demanda, unnest(COALESCE(v_ids, '{}'::integer[]))
    ON CONFLICT (demanda_id, pedido_id) DO NOTHING;

    SELECT array_agg(dp.pedido_id ORDER BY dp.pedido_id) INTO v_todos_ids
      FROM public.demandas_pedidos dp WHERE dp.demanda_id = v_demanda;

    IF COALESCE(array_length(v_todos_ids, 1), 0) = 0 THEN
        RAISE EXCEPTION 'Escopo vazio: nenhum pedido disponivel para lancamento'
            USING ERRCODE = 'no_data_found', DETAIL = v_conflitos::text;
    END IF;

    -- 6. Materializa pelo MESMO caminho da torre.
    --    Recalcula sobre o conjunto inteiro: o rank do miolo depende da carga
    --    total do lote, entao acrescentar linhas isoladamente daria uma ordem
    --    de producao errada.
    DELETE FROM public.demandas_item_origem
     WHERE demanda_item_id IN (
        SELECT id FROM public.itens_demanda WHERE demanda_id = v_demanda);
    DELETE FROM public.itens_demanda WHERE demanda_id = v_demanda;

    v_total_itens := public.despacho_materializar_itens(v_demanda, v_todos_ids);

    SELECT jsonb_agg(jsonb_build_object(
             'integration_id',   t.marketplace_integration_id,
             'marketplace_nome', COALESCE(btrim(ii.instance_name), 'Origem nao resolvida'),
             'modalidade_id',    t.modalidade_logistica_id,
             'modalidade_nome',  COALESCE(m.nome, 'Modalidade nao classificada'),
             'qtd_pedidos',      t.qtd) ORDER BY t.qtd DESC)
      INTO v_nos
      FROM (
        SELECT p.marketplace_integration_id, p.modalidade_logistica_id, count(*) AS qtd
          FROM public.pedidos p WHERE p.id = ANY(v_todos_ids)
         GROUP BY 1, 2
      ) t
      LEFT JOIN public.installed_integrations ii ON ii.id = t.marketplace_integration_id
      LEFT JOIN public.modalidades_logisticas  m ON m.id  = t.modalidade_logistica_id;

    UPDATE public.demandas_producao
       SET escopo_despacho = COALESCE(p_escopo, '{}'::jsonb) || jsonb_build_object(
               'origem',         COALESCE(NULLIF(p_escopo ->> 'origem', ''), 'ARQUIVO'),
               'integration_id', v_integration_id,
               'modalidade_id',  v_modalidade_id,
               'nos',            COALESCE(v_nos, '[]'::jsonb),
               'total_pedidos',  COALESCE(array_length(v_todos_ids, 1), 0),
               'montado_por',    p_user_id,
               'montado_em',     now()),
           canal_venda_id = COALESCE(canal_venda_id, v_canal_id),
           modalidade_id  = COALESCE(modalidade_id, v_modalidade_id),
           pedido_numero  = COALESCE(array_length(v_todos_ids, 1), 0)::text || ' pedidos',
           updated_at     = now()
     WHERE id = v_demanda;

    SELECT d.demanda_id INTO v_codigo
      FROM public.demandas_producao d WHERE d.id = v_demanda;

    -- despachado_em NAO e carimbado aqui: rascunho nao e despacho.
    RETURN QUERY SELECT v_demanda, v_codigo,
                        COALESCE(array_length(v_todos_ids, 1), 0),
                        COALESCE(v_total_itens, 0), v_somou, v_conflitos;
END;
$$;


ALTER FUNCTION "public"."despacho_lancar_pedidos"("p_pedido_ids" integer[], "p_nome" "text", "p_user_id" "text", "p_observacoes" "text", "p_escopo" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_lancar_pedidos"("p_pedido_ids" integer[], "p_nome" "text", "p_user_id" "text", "p_observacoes" "text", "p_escopo" "jsonb") IS 'Monta um RASCUNHO a partir de uma selecao explicita de pedidos (ex.: recorte de planilha). Recorta, recusa pedidos ja presentes em outro rascunho e delega a materializacao para despacho_materializar_itens — o mesmo caminho do lancamento pela torre.';



CREATE OR REPLACE FUNCTION "public"."despacho_lotes"("p_integration_id" integer) RETURNS TABLE("modalidade_id" integer, "lote_chave" "text", "modalidade_ids" integer[], "lote_nome" "text", "entrega_rapida" boolean)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
WITH pares AS (
    -- duas modalidades pertencem ao mesmo lote quando compartilham uma janela
    SELECT a.modalidade_id AS m, b.modalidade_id AS parceira
      FROM public.regra_logistica_modalidades a
      JOIN public.regras_logisticas_integracao r ON r.id = a.regra_id
      JOIN public.regra_logistica_modalidades b ON b.regra_id = a.regra_id
     WHERE r.ativo AND r.marketplace_integration_id = p_integration_id
),
grupos AS (
    SELECT m, array_agg(DISTINCT parceira ORDER BY parceira) AS ids
      FROM pares GROUP BY m
)
SELECT g.m,
       array_to_string(g.ids, ','),
       g.ids,
       (SELECT string_agg(ml.nome, ' + ' ORDER BY ml.ordem_exibicao, ml.nome)
          FROM public.modalidades_logisticas ml WHERE ml.id = ANY (g.ids)),
       -- Um lote e rapido se qualquer canal dele for: o caminhao nao espera.
       (SELECT bool_or(COALESCE(ml.entrega_rapida, false))
          FROM public.modalidades_logisticas ml WHERE ml.id = ANY (g.ids))
  FROM grupos g;
$$;


ALTER FUNCTION "public"."despacho_lotes"("p_integration_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_lotes"("p_integration_id" integer) IS 'Agrupamento de canais em lotes por conta: duas modalidades sao o mesmo lote quando compartilham uma janela ativa. lote_chave e a lista ordenada de ids, usada como identidade do card da torre e do rascunho aberto.';



CREATE OR REPLACE FUNCTION "public"."despacho_materializar_itens"("p_demanda_id" integer, "p_pedido_ids" integer[], "p_ajustes" "jsonb" DEFAULT NULL::"jsonb") RETURNS numeric
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_total  numeric := 0;
    v_op     jsonb;
    v_acao   text;
    v_sku    text;
    v_var    text;
    v_miolo  text;
    v_tit    text;
    v_n      integer;
    v_linha  record;
    v_comp   record;
    v_qtd    numeric;
    v_alvo   tid;
    v_houve  boolean := false;
BEGIN
    DROP TABLE IF EXISTS _cons_lote;
    CREATE TEMP TABLE _cons_lote ON COMMIT DROP AS
      SELECT * FROM public.despacho_consolidar_pedidos(p_pedido_ids);

    IF p_ajustes IS NOT NULL AND jsonb_typeof(p_ajustes) = 'array'
       AND jsonb_array_length(p_ajustes) > 0 THEN

      FOR v_op IN SELECT value FROM jsonb_array_elements(p_ajustes) LOOP
        v_acao  := lower(coalesce(v_op ->> 'op', ''));
        v_sku   := coalesce(v_op ->> 'sku', '-');
        v_var   := coalesce(v_op ->> 'variacao', '-');
        v_miolo := v_op ->> 'miolo_chave';
        v_tit   := nullif(btrim(coalesce(v_op ->> 'titulo', '')), '');

        SELECT count(*) INTO v_n FROM _cons_lote c
         WHERE c.sku_externo = v_sku AND c.variacao = v_var
           AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
           AND (v_tit IS NULL OR c.titulo_anuncio = v_tit);

        IF v_n = 0 THEN
          RAISE EXCEPTION 'Ajuste referencia uma linha que nao existe no lote: % / % / %',
            v_sku, v_var, coalesce(v_miolo, '(sem miolo)') USING ERRCODE = 'no_data_found';
        END IF;

        IF v_acao = 'quantidade' AND v_n > 1 THEN
          RAISE EXCEPTION 'O SKU % tem % linhas neste lote; informe "titulo" para dizer qual delas ajustar',
            v_sku, v_n USING ERRCODE = 'check_violation';
        END IF;

        IF v_acao = 'remover' THEN
          DELETE FROM _cons_lote c
           WHERE c.sku_externo = v_sku AND c.variacao = v_var
             AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
             AND (v_tit IS NULL OR c.titulo_anuncio = v_tit);
          v_houve := true;

        ELSIF v_acao = 'quantidade' THEN
          v_qtd := coalesce((v_op ->> 'valor')::numeric, 0);
          IF v_qtd <= 0 THEN
            RAISE EXCEPTION 'Quantidade ajustada deve ser maior que zero (linha %)', v_sku
              USING ERRCODE = 'check_violation';
          END IF;
          UPDATE _cons_lote c SET quantidade = v_qtd
           WHERE c.sku_externo = v_sku AND c.variacao = v_var
             AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
             AND (v_tit IS NULL OR c.titulo_anuncio = v_tit);
          v_houve := true;

        ELSIF v_acao = 'explodir' THEN
          FOR v_linha IN
            SELECT * FROM _cons_lote c
             WHERE c.sku_externo = v_sku AND c.variacao = v_var
               AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
               AND (v_tit IS NULL OR c.titulo_anuncio = v_tit)
          LOOP
            IF v_linha.produto_id IS NULL THEN
              RAISE EXCEPTION 'Nao da para explodir uma linha sem produto interno vinculado (%)', v_sku
                USING ERRCODE = 'check_violation';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM public.despacho_kit_componentes(v_linha.produto_id)) THEN
              RAISE EXCEPTION 'Produto % nao tem componentes de produto acabado para explodir', v_sku
                USING ERRCODE = 'check_violation';
            END IF;

            FOR v_comp IN SELECT * FROM public.despacho_kit_componentes(v_linha.produto_id) LOOP
              v_qtd := v_linha.quantidade * coalesce(v_comp.quantidade, 1);

              -- Uma linha alvo por vez: somar em todas as linhas do mesmo
              -- produto inflaria a quantidade quando o produto aparece com
              -- mais de um titulo de anuncio.
              SELECT c.ctid INTO v_alvo FROM _cons_lote c
               WHERE c.produto_id = v_comp.produto_id
               ORDER BY c.quantidade DESC, c.ctid LIMIT 1;

              IF v_alvo IS NOT NULL THEN
                UPDATE _cons_lote c
                   SET quantidade     = c.quantidade + v_qtd,
                       itens_origem   = ARRAY(SELECT DISTINCT unnest(c.itens_origem   || v_linha.itens_origem)   ORDER BY 1),
                       pedidos_origem = ARRAY(SELECT DISTINCT unnest(c.pedidos_origem || v_linha.pedidos_origem) ORDER BY 1)
                 WHERE c.ctid = v_alvo;
              ELSE
                INSERT INTO _cons_lote (
                  ordem, miolo, miolo_chave, miolo_rank, miolo_total, titulo_anuncio,
                  sku_externo, variacao, quantidade, produto_id, produto_nome,
                  id_produto_miolo, miolo_origem, contabiliza_estoque,
                  pedidos_origem, itens_origem
                ) VALUES (
                  0, coalesce(v_comp.miolo_nome, v_comp.miolo_chave),
                  coalesce(v_comp.miolo_chave, v_linha.miolo_chave),
                  0, 0, v_comp.nome, v_comp.sku, '-', v_qtd,
                  v_comp.produto_id, v_comp.nome, v_comp.id_produto_miolo,
                  CASE WHEN v_comp.id_produto_miolo IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
                  true, v_linha.pedidos_origem, v_linha.itens_origem
                );
              END IF;
              v_alvo := NULL;
            END LOOP;

            DELETE FROM _cons_lote c WHERE c.ctid = v_linha.ctid;
          END LOOP;
          v_houve := true;

        ELSE
          RAISE EXCEPTION 'Operacao de ajuste desconhecida: %', v_acao
            USING ERRCODE = 'check_violation';
        END IF;
      END LOOP;
    END IF;

    IF v_houve THEN
      IF NOT EXISTS (SELECT 1 FROM _cons_lote) THEN
        RAISE EXCEPTION 'Os ajustes removeriam todas as linhas do lote'
          USING ERRCODE = 'check_violation';
      END IF;

      WITH r AS (
        SELECT miolo_chave, sum(quantidade) AS total,
               row_number() OVER (ORDER BY sum(quantidade) DESC, miolo_chave)::integer AS rank
          FROM _cons_lote GROUP BY miolo_chave
      )
      UPDATE _cons_lote c
         SET miolo_rank = r.rank, miolo_total = r.total
        FROM r WHERE r.miolo_chave IS NOT DISTINCT FROM c.miolo_chave;

      WITH o AS (
        SELECT ctid, row_number() OVER (ORDER BY miolo_rank, quantidade DESC,
                                        sku_externo, variacao, titulo_anuncio)::integer AS n
          FROM _cons_lote
      )
      UPDATE _cons_lote c SET ordem = o.n FROM o WHERE o.ctid = c.ctid;
    END IF;

    WITH ins AS (
        INSERT INTO public.itens_demanda (
            demanda_id, ordem, produto_id, sku, sku_externo, descricao, variacao,
            quantidade, quantidade_planejada, miolo_nome, miolo_chave, miolo_origem,
            id_produto_miolo, contabiliza_estoque, dados_adicionais
        )
        SELECT p_demanda_id, c.ordem, c.produto_id, c.sku_externo, c.sku_externo,
               c.titulo_anuncio, c.variacao, c.quantidade, c.quantidade,
               c.miolo, c.miolo_chave, c.miolo_origem, c.id_produto_miolo,
               c.contabiliza_estoque,
               jsonb_build_object('miolo_rank', c.miolo_rank,
                                  'miolo_carga', c.miolo_total,
                                  'produto_nome', c.produto_nome)
          FROM _cons_lote c
        RETURNING id, ordem
    )
    INSERT INTO public.demandas_item_origem (
        demanda_item_id, plataforma, pedido_id, pedido_externo_id,
        item_externo_id, sku_externo, quantidade_atendida
    )
    SELECT i.id, p.origem, p.id, p.codigo_pedido_externo,
           ip.item_externo_id, ip.sku_externo, ip.quantidade
      FROM ins i
      JOIN _cons_lote c ON c.ordem = i.ordem
     CROSS JOIN LATERAL unnest(c.itens_origem) AS oi(item_id)
      JOIN public.itens_pedido ip ON ip.id = oi.item_id
      JOIN public.pedidos      p  ON p.id  = ip.pedido_id;

    SELECT COALESCE(sum(quantidade), 0) INTO v_total
      FROM public.itens_demanda WHERE demanda_id = p_demanda_id;

    DROP TABLE IF EXISTS _cons_lote;
    RETURN v_total;
END;
$$;


ALTER FUNCTION "public"."despacho_materializar_itens"("p_demanda_id" integer, "p_pedido_ids" integer[], "p_ajustes" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_materializar_itens"("p_demanda_id" integer, "p_pedido_ids" integer[], "p_ajustes" "jsonb") IS 'Materializa os itens da demanda a partir da consolidacao canonica. p_ajustes NULL reproduz o comportamento anterior byte a byte; com ajustes, aplica remover/quantidade/explodir sobre o resultado e renumera a ordem.';



CREATE OR REPLACE FUNCTION "public"."despacho_publicar_demanda"("p_demanda_id" integer, "p_user_id" "text" DEFAULT 'System'::"text") RETURNS TABLE("out_demanda_codigo" "text", "out_total_pedidos" integer, "out_total_itens" numeric)
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE v_status text; v_codigo text; v_ids integer[];
BEGIN
    SELECT d.status, d.demanda_id INTO v_status, v_codigo
      FROM public.demandas_producao d WHERE d.id = p_demanda_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE='no_data_found';
    END IF;
    IF v_status <> 'RASCUNHO' THEN
        RAISE EXCEPTION 'Demanda % ja esta em %; so rascunho pode ser publicado', v_codigo, v_status
            USING ERRCODE='invalid_parameter_value';
    END IF;

    SELECT array_agg(dp.pedido_id) INTO v_ids
      FROM public.demandas_pedidos dp WHERE dp.demanda_id = p_demanda_id;
    IF COALESCE(array_length(v_ids,1),0) = 0 THEN
        RAISE EXCEPTION 'Demanda % nao tem pedidos', v_codigo USING ERRCODE='no_data_found';
    END IF;

    UPDATE public.demandas_producao
       SET status = 'AGUARDANDO',
           publicado_em = now(),
           -- publicado_por e integer (id de usuario); o ator textual do fluxo de
           -- despacho fica no escopo, junto de quem montou o rascunho.
           escopo_despacho = COALESCE(escopo_despacho,'{}'::jsonb)
                             || jsonb_build_object('publicado_por', p_user_id, 'publicado_em', now()),
           updated_at = now()
     WHERE id = p_demanda_id;

    -- Publicar e o momento em que o galpao assume o lote. So aqui o pedido sai
    -- da torre.
    UPDATE public.pedidos SET despachado_em = now()
     WHERE id = ANY(v_ids) AND despachado_em IS NULL;

    RETURN QUERY SELECT v_codigo, COALESCE(array_length(v_ids,1),0),
        COALESCE((SELECT sum(quantidade) FROM public.itens_demanda WHERE demanda_id=p_demanda_id),0);
END;
$$;


ALTER FUNCTION "public"."despacho_publicar_demanda"("p_demanda_id" integer, "p_user_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_publicar_demanda"("p_demanda_id" integer, "p_user_id" "text") IS 'Publica um rascunho: RASCUNHO -> AGUARDANDO e carimba despachado_em nos pedidos, que e o momento em que eles saem da torre. Recusa demanda que nao esteja em rascunho.';



CREATE OR REPLACE FUNCTION "public"."despacho_rascunhos_abertos"("p_data" "date" DEFAULT CURRENT_DATE) RETURNS TABLE("integration_id" integer, "modalidade_id" integer, "demanda_pk" integer, "demanda_codigo" "text", "montado_em" timestamp with time zone, "montado_por" "text", "qtd_pedidos" integer, "qtd_itens" numeric, "qtd_linhas" integer, "pedidos_ja_fora" integer)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT
        (d.escopo_despacho ->> 'integration_id')::integer,
        d.modalidade_id,
        d.id,
        d.demanda_id,
        (d.escopo_despacho ->> 'montado_em')::timestamptz,
        d.escopo_despacho ->> 'montado_por',
        (SELECT count(*)::integer FROM public.demandas_pedidos dp WHERE dp.demanda_id = d.id),
        COALESCE((SELECT sum(i.quantidade) FROM public.itens_demanda i WHERE i.demanda_id = d.id), 0),
        (SELECT count(*)::integer FROM public.itens_demanda i WHERE i.demanda_id = d.id),
        (SELECT count(*)::integer
           FROM public.demandas_pedidos dp
           JOIN public.pedidos p ON p.id = dp.pedido_id
          WHERE dp.demanda_id = d.id
            AND (p.situacao_pedido_id <> 2 OR p.despachado_em IS NOT NULL))
      FROM public.demandas_producao d
     WHERE d.status = 'RASCUNHO'
       AND d.escopo_despacho ->> 'data_operacional' = p_data::text;
$$;


ALTER FUNCTION "public"."despacho_rascunhos_abertos"("p_data" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_rascunhos_abertos"("p_data" "date") IS 'Rascunhos abertos por no da torre, para o card sinalizar "N ja em rascunho" sem alterar a contagem de pedidos. pedidos_ja_fora conta os que sairam da pendencia depois de entrarem no rascunho — cancelados, devolvidos ou enviados por fora — e e a checagem que o operador precisa ver antes de publicar.';



CREATE OR REPLACE FUNCTION "public"."despacho_reaplicar_itens"("p_demanda_id" integer, "p_ajustes" "jsonb", "p_user_id" "text" DEFAULT 'System'::"text") RETURNS numeric
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_status text;
    v_ids    integer[];
    v_total  numeric;
BEGIN
    SELECT d.status INTO v_status FROM public.demandas_producao d WHERE d.id = p_demanda_id;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_status <> 'RASCUNHO' THEN
        RAISE EXCEPTION 'Demanda % ja foi publicada; a lista de itens nao pode mais ser editada', p_demanda_id
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT array_agg(dp.pedido_id ORDER BY dp.pedido_id) INTO v_ids
      FROM public.demandas_pedidos dp WHERE dp.demanda_id = p_demanda_id;

    IF coalesce(array_length(v_ids, 1), 0) = 0 THEN
        RAISE EXCEPTION 'Demanda % nao tem pedidos vinculados', p_demanda_id
            USING ERRCODE = 'no_data_found';
    END IF;

    DELETE FROM public.demandas_item_origem
     WHERE demanda_item_id IN (SELECT id FROM public.itens_demanda WHERE demanda_id = p_demanda_id);
    DELETE FROM public.itens_demanda WHERE demanda_id = p_demanda_id;

    v_total := public.despacho_materializar_itens(p_demanda_id, v_ids, p_ajustes);

    UPDATE public.demandas_producao
       SET escopo_despacho = coalesce(escopo_despacho, '{}'::jsonb)
                             || jsonb_build_object('ajustes', coalesce(p_ajustes, '[]'::jsonb),
                                                   'ajustado_por', p_user_id,
                                                   'ajustado_em', now()),
           editado_pelo_usuario = (p_ajustes IS NOT NULL AND jsonb_array_length(coalesce(p_ajustes,'[]'::jsonb)) > 0),
           editado_em = now(),
           updated_at = now()
     WHERE id = p_demanda_id;

    RETURN v_total;
END;
$$;


ALTER FUNCTION "public"."despacho_reaplicar_itens"("p_demanda_id" integer, "p_ajustes" "jsonb", "p_user_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_reaplicar_itens"("p_demanda_id" integer, "p_ajustes" "jsonb", "p_user_id" "text") IS 'Refaz os itens de um rascunho aplicando os ajustes do operador. Recusa demanda ja publicada.';



CREATE OR REPLACE FUNCTION "public"."despacho_recalcular_compromissos"() RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_qtd integer;
BEGIN
    WITH alvo AS (
        SELECT p.id, j.corte_em
          FROM public.pedidos p
          JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
          CROSS JOIN LATERAL public.proxima_janela_logistica(
                        p.modalidade_logistica_id, p.marketplace_integration_id, now()
                    ) j
         WHERE p.despachado_em IS NULL
           AND p.situacao_pedido_id IN (2, 3, 4)
           AND m.tipo_prazo = 'FIXO'
           AND p.compromisso_logistico_em IS DISTINCT FROM j.corte_em
    )
    UPDATE public.pedidos p
       SET compromisso_logistico_em = a.corte_em
      FROM alvo a
     WHERE p.id = a.id;

    GET DIAGNOSTICS v_qtd = ROW_COUNT;
    RETURN v_qtd;
END;
$$;


ALTER FUNCTION "public"."despacho_recalcular_compromissos"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_recalcular_compromissos"() IS 'Regrava compromisso_logistico_em dos pedidos FIXO pendentes. So para consumidores legados: a torre calcula na leitura e nao depende desta rotina.';



CREATE OR REPLACE FUNCTION "public"."despacho_sincronizar_carimbo"("p_pedido_ids" integer[]) RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_alterados integer;
BEGIN
    IF COALESCE(array_length(p_pedido_ids, 1), 0) = 0 THEN
        RETURN 0;
    END IF;

    WITH alvo AS (
        SELECT p.id,
               p.despachado_em,
               EXISTS (
                   SELECT 1
                     FROM public.demandas_pedidos dp
                     JOIN public.demandas_producao d ON d.id = dp.demanda_id
                    WHERE dp.pedido_id = p.id
                      AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
               ) AS deveria_estar_despachado
          FROM public.pedidos p
         WHERE p.id = ANY(p_pedido_ids)
    ),
    aplicado AS (
        UPDATE public.pedidos p
           -- Carimbo existente e preservado: a data em que o galpao assumiu o
           -- lote e fato historico e nao pode ser reescrita por um recalculo.
           SET despachado_em = CASE WHEN a.deveria_estar_despachado THEN now() END
          FROM alvo a
         WHERE p.id = a.id
           AND a.deveria_estar_despachado <> (a.despachado_em IS NOT NULL)
        RETURNING p.id
    )
    SELECT count(*) INTO v_alterados FROM aplicado;

    RETURN v_alterados;
END;
$$;


ALTER FUNCTION "public"."despacho_sincronizar_carimbo"("p_pedido_ids" integer[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."despacho_sincronizar_carimbo"("p_pedido_ids" integer[]) IS 'Recalcula pedidos.despachado_em a partir de demandas_pedidos + status da demanda. Carimbo ja existente e preservado; so a transicao e escrita.';



CREATE OR REPLACE FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp without time zone, "p_created_at" timestamp without time zone) RETURNS timestamp with time zone
    LANGUAGE "sql" IMMUTABLE PARALLEL SAFE
    AS $$
    SELECT COALESCE(p_data_compra_marketplace, p_data_venda, p_created_at);
$$;


ALTER FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp without time zone, "p_created_at" timestamp without time zone) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp with time zone, "p_created_at" timestamp with time zone) RETURNS timestamp with time zone
    LANGUAGE "sql" IMMUTABLE STRICT PARALLEL SAFE
    AS $$
    SELECT COALESCE(p_data_compra_marketplace, p_data_venda, p_created_at);
$$;


ALTER FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp with time zone, "p_created_at" timestamp with time zone) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enforce_marketplace_order_authority"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  IF lower(COALESCE(OLD.ingest_source, '')) IN ('shopee', 'mercadolivre')
     AND lower(COALESCE(NEW.ingest_source, '')) = 'bling' THEN
    NEW.ingest_source := OLD.ingest_source;
    NEW.marketplace_integration_id := COALESCE(OLD.marketplace_integration_id, NEW.marketplace_integration_id);
    NEW.situacao_pedido_id := OLD.situacao_pedido_id;
    NEW.status_original := OLD.status_original;
    NEW.total_pedido := OLD.total_pedido;
    NEW.moeda := OLD.moeda;
    NEW.data_venda := OLD.data_venda;
    NEW.cliente_nome := OLD.cliente_nome;
    NEW.cliente_documento := OLD.cliente_documento;
    NEW.cliente_telefone := OLD.cliente_telefone;
    NEW.cliente_email := OLD.cliente_email;
    NEW.informacoes_cliente := OLD.informacoes_cliente;
    NEW.is_flex := OLD.is_flex;
    NEW.is_fulfillment := OLD.is_fulfillment;
    NEW.modalidade_logistica := OLD.modalidade_logistica;
    NEW.servico_logistico := OLD.servico_logistico;
    NEW.data_limite_envio := OLD.data_limite_envio;
    NEW.data_compra_marketplace := OLD.data_compra_marketplace;
    NEW.data_pagamento_marketplace := OLD.data_pagamento_marketplace;
    NEW.data_coleta := OLD.data_coleta;
    NEW.data_envio_marketplace := OLD.data_envio_marketplace;
    NEW.regra_logistica_integracao_id := OLD.regra_logistica_integracao_id;
    NEW.personalizado := OLD.personalizado;
    NEW.canal_venda_id := COALESCE(OLD.canal_venda_id, NEW.canal_venda_id);
    NEW.buyer_username := OLD.buyer_username;
    NEW.shipping_carrier := OLD.shipping_carrier;
    NEW.message_to_seller := OLD.message_to_seller;
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."enforce_marketplace_order_authority"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enrich_order_erp_reference"("p_pedido_id" bigint, "p_erp_integration_id" integer, "p_erp_store_id" "text", "p_erp_order_id" bigint, "p_erp_order_number" "text", "p_marketplace_order_id" "text" DEFAULT NULL::"text") RETURNS bigint
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public'
    AS $_$
DECLARE
  v_pedido_id BIGINT;
  v_pedido_bling_id INTEGER;
  v_pack_id TEXT;
BEGIN
  SELECT id, pack_id INTO v_pedido_id, v_pack_id
  FROM public.pedidos
  WHERE id = p_pedido_id
     OR (p_marketplace_order_id IS NOT NULL
         AND marketplace_order_id = p_marketplace_order_id)
  ORDER BY CASE WHEN id = p_pedido_id THEN 0 ELSE 1 END, id
  LIMIT 1
  FOR UPDATE;

  IF v_pedido_id IS NULL THEN
    RAISE EXCEPTION 'Pedido canonico nao encontrado para enriquecimento';
  END IF;

  INSERT INTO public.pedidos_bling (
    numero_pedido, loja_id, bling_id, numero_loja, raw_payload,
    bling_integration_id, updated_at
  ) VALUES (
    p_erp_order_number,
    CASE WHEN COALESCE(p_erp_store_id, '') ~ '^[0-9]+$'
         THEN p_erp_store_id::INTEGER ELSE NULL END,
    p_erp_order_id,
    p_marketplace_order_id,
    jsonb_build_object(
      'reference_only', true,
      'id', p_erp_order_id,
      'numero', p_erp_order_number,
      'numeroLoja', p_marketplace_order_id,
      'loja_id', p_erp_store_id
    ),
    p_erp_integration_id,
    now()
  )
  ON CONFLICT (bling_integration_id, bling_id)
  DO UPDATE SET
    numero_pedido = EXCLUDED.numero_pedido,
    loja_id = COALESCE(EXCLUDED.loja_id, public.pedidos_bling.loja_id),
    numero_loja = COALESCE(EXCLUDED.numero_loja, public.pedidos_bling.numero_loja),
    raw_payload = public.pedidos_bling.raw_payload || EXCLUDED.raw_payload,
    updated_at = now()
  RETURNING id INTO v_pedido_bling_id;

  -- Um pacote e uma caixa: os pedidos irmaos vao no mesmo envio e sao faturados
  -- sob o mesmo pedido do ERP. Aplicar a referencia no pacote inteiro de uma vez
  -- resolve os irmaos na primeira passada, em vez de deixa-los tentando
  -- reivindicar o mesmo registro em rodadas seguintes.
  UPDATE public.pedidos
     SET erp_integration_id = p_erp_integration_id,
         erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id,
         erp_order_number = p_erp_order_number,
         numero_pedido = p_erp_order_number,
         pedido_bling_id = v_pedido_bling_id,
         updated_at = now()
   WHERE id = v_pedido_id
      OR (v_pack_id IS NOT NULL AND pack_id = v_pack_id AND erp_order_id IS NULL);

  UPDATE public.pedido_snapshots
     SET identity = identity || jsonb_build_object(
           'erp_integration_id', p_erp_integration_id,
           'erp_store_id', p_erp_store_id,
           'erp_order_id', p_erp_order_id,
           'erp_order_number', p_erp_order_number
         ),
         raw_refs = raw_refs || jsonb_build_object(
           'bling_lookup', jsonb_build_object(
             'status', 'found',
             'erp_integration_id', p_erp_integration_id,
             'erp_order_id', p_erp_order_id,
             'erp_order_number', p_erp_order_number,
             'numero_loja', p_marketplace_order_id
           )
         ),
         updated_at = now()
   WHERE pedido_id IN (
       SELECT id FROM public.pedidos
        WHERE id = v_pedido_id
           OR (v_pack_id IS NOT NULL AND pack_id = v_pack_id)
   );

  INSERT INTO public.pedido_integration_refs (
    pedido_id, integration_id, module_id, role, external_order_id,
    external_record_id, metadata, last_synced_at
  )
  SELECT pd.id, p_erp_integration_id, 'bling', 'erp',
         pd.marketplace_order_id, p_erp_order_id::TEXT,
         jsonb_build_object('store_id', p_erp_store_id, 'order_number', p_erp_order_number),
         now()
    FROM public.pedidos pd
   WHERE p_erp_integration_id IS NOT NULL
     AND (pd.id = v_pedido_id
          OR (v_pack_id IS NOT NULL AND pd.pack_id = v_pack_id))
  ON CONFLICT (pedido_id, integration_id, role)
  DO UPDATE SET
    external_order_id = EXCLUDED.external_order_id,
    external_record_id = EXCLUDED.external_record_id,
    metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
    last_synced_at = now(),
    updated_at = now();

  -- Encerra a fila do pedido e a dos irmaos do pacote.
  UPDATE public.pending_order_reconciliations t
     SET status = 'applied', resolved_at = now(), updated_at = now(), last_error = NULL,
         erp_integration_id = p_erp_integration_id, erp_store_id = p_erp_store_id,
         erp_order_id = p_erp_order_id
   WHERE t.status = 'pending'
     AND (
       t.pedido_id IN (
         SELECT id FROM public.pedidos
          WHERE id = v_pedido_id
             OR (v_pack_id IS NOT NULL AND pack_id = v_pack_id)
       )
       OR (
         t.erp_integration_id = p_erp_integration_id
         AND t.erp_store_id = p_erp_store_id
         AND t.erp_order_id = p_erp_order_id
       )
     );

  RETURN v_pedido_id;
END;
$_$;


ALTER FUNCTION "public"."enrich_order_erp_reference"("p_pedido_id" bigint, "p_erp_integration_id" integer, "p_erp_store_id" "text", "p_erp_order_id" bigint, "p_erp_order_number" "text", "p_marketplace_order_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."enrich_order_erp_reference"("p_pedido_id" bigint, "p_erp_integration_id" integer, "p_erp_store_id" "text", "p_erp_order_id" bigint, "p_erp_order_number" "text", "p_marketplace_order_id" "text") IS 'Aplica a referencia de ERP no pedido e nos irmaos do mesmo pacote. Um pacote e uma caixa: um pedido no ERP, N pedidos canonicos.';



CREATE OR REPLACE FUNCTION "public"."extrair_metodo_envio"("p_module_id" "text", "p_platform_fields" "jsonb") RETURNS TABLE("chave" "text", "rotulo" "text", "campo_origem" "text")
    LANGUAGE "sql" IMMUTABLE
    AS $$
    SELECT
        CASE p_module_id
            WHEN 'shopee' THEN
                COALESCE(
                    p_platform_fields -> 'shopee' -> 'package_list' -> 0 ->> 'logistics_channel_id',
                    p_platform_fields -> 'shopee' ->> 'logistics_channel_id'
                )
            WHEN 'mercadolivre' THEN
                COALESCE(
                    p_platform_fields -> 'mercadolivre' -> 'shipment' -> 'logistic' ->> 'type',
                    p_platform_fields -> 'mercadolivre' -> 'shipment' ->> 'logistic_type'
                )
        END,
        CASE p_module_id
            WHEN 'shopee' THEN
                COALESCE(
                    p_platform_fields -> 'shopee' -> 'package_list' -> 0 ->> 'shipping_carrier',
                    p_platform_fields -> 'shopee' ->> 'shipping_carrier'
                )
            WHEN 'mercadolivre' THEN
                COALESCE(
                    p_platform_fields -> 'mercadolivre' -> 'shipment' -> 'shipping_option' ->> 'name',
                    p_platform_fields -> 'mercadolivre' -> 'shipment' ->> 'mode'
                )
        END,
        CASE p_module_id
            WHEN 'shopee'       THEN 'logistics_channel_id'
            WHEN 'mercadolivre' THEN 'logistic.type'
        END;
$$;


ALTER FUNCTION "public"."extrair_metodo_envio"("p_module_id" "text", "p_platform_fields" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."extrair_metodo_envio"("p_module_id" "text", "p_platform_fields" "jsonb") IS 'Le a chave estavel de metodo de envio do payload cru. Mesmos caminhos do extrator Python; existe aqui para a classificacao nao depender de deploy do worker.';



CREATE OR REPLACE FUNCTION "public"."finalize_ingest_archive_batch"("p_dataset" "text", "p_ids" "text"[], "p_object_key" "text", "p_sha256" "text", "p_period_start" "date", "p_period_end" "date", "p_row_count" bigint, "p_schema_version" integer DEFAULT 1) RETURNS bigint
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE manifest_id bigint;
BEGIN
  IF COALESCE(array_length(p_ids, 1), 0) = 0 THEN
    RAISE EXCEPTION 'archive batch cannot be empty';
  END IF;
  IF p_row_count <> array_length(p_ids, 1) THEN
    RAISE EXCEPTION 'row count does not match id count';
  END IF;

  INSERT INTO public.archive_manifests (
    dataset, period_start, period_end, object_key, row_count, sha256, schema_version
  ) VALUES (
    p_dataset, p_period_start, p_period_end, p_object_key, p_row_count, p_sha256,
    COALESCE(p_schema_version, 1)
  )
  ON CONFLICT (dataset, object_key) DO NOTHING
  RETURNING id INTO manifest_id;

  IF manifest_id IS NULL THEN
    SELECT id INTO manifest_id FROM public.archive_manifests
    WHERE dataset = p_dataset AND object_key = p_object_key
      AND sha256 = p_sha256 AND row_count = p_row_count;
    IF manifest_id IS NULL THEN
      RAISE EXCEPTION 'archive manifest conflict for %', p_object_key;
    END IF;
  END IF;

  CASE p_dataset
    WHEN 'webhook_payloads' THEN
      UPDATE public.webhook_events
      SET raw_payload = '{}'::jsonb, raw_body = NULL, raw_archived_at = now(),
          archive_object_key = p_object_key
      WHERE id = ANY(p_ids::bigint[]) AND raw_archived_at IS NULL;
    WHEN 'shopee_chat_payloads' THEN
      UPDATE public.mensagem_chat_shopee
      SET raw_json = NULL, raw_payload = NULL, raw_archived_at = now(),
          archive_object_key = p_object_key
      WHERE id = ANY(p_ids) AND raw_archived_at IS NULL;
    WHEN 'webhook_event_attempts' THEN
      DELETE FROM public.webhook_event_attempts WHERE id = ANY(p_ids::bigint[]);
    WHEN 'task_execution_logs' THEN
      DELETE FROM public.task_execution_logs WHERE id = ANY(p_ids::uuid[]);
    WHEN 'pedido_ingest_log' THEN
      DELETE FROM public.pedido_ingest_log WHERE id = ANY(p_ids::bigint[]);
    WHEN 'integration_refresh_logs' THEN
      DELETE FROM public.integration_refresh_logs WHERE id = ANY(p_ids::integer[]);
    ELSE
      RAISE EXCEPTION 'unsupported archive dataset: %', p_dataset;
  END CASE;
  RETURN manifest_id;
END;
$$;


ALTER FUNCTION "public"."finalize_ingest_archive_batch"("p_dataset" "text", "p_ids" "text"[], "p_object_key" "text", "p_sha256" "text", "p_period_start" "date", "p_period_end" "date", "p_row_count" bigint, "p_schema_version" integer) OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."installed_integrations" (
    "id" integer NOT NULL,
    "module_id" character varying(100) NOT NULL,
    "instance_name" character varying(255) NOT NULL,
    "user_id" character varying(255),
    "config" "jsonb" DEFAULT '{}'::"jsonb",
    "access_token" "text",
    "refresh_token" "text",
    "expires_at" timestamp with time zone,
    "is_active" boolean DEFAULT true,
    "last_sync" timestamp with time zone,
    "sync_status" character varying(50) DEFAULT 'pending'::character varying,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "credentials" "jsonb" DEFAULT '{}'::"jsonb",
    "last_refresh_attempt" timestamp with time zone,
    "refresh_error" "text",
    "instance_color" character varying(20) DEFAULT '#64748b'::character varying,
    "description" "text",
    "parent_integration_id" integer,
    "is_default" boolean DEFAULT false,
    "functional_scopes" "jsonb" DEFAULT '[]'::"jsonb",
    "platform_slug" character varying(100),
    "is_placeholder" boolean DEFAULT false,
    "app_profile_id" bigint
);


ALTER TABLE "public"."installed_integrations" OWNER TO "postgres";


COMMENT ON COLUMN "public"."installed_integrations"."credentials" IS 'Platform-specific metadata and raw responses';



COMMENT ON COLUMN "public"."installed_integrations"."last_refresh_attempt" IS 'Timestamp of the last token refresh attempt';



COMMENT ON COLUMN "public"."installed_integrations"."refresh_error" IS 'Error message from the last failed refresh attempt';



COMMENT ON COLUMN "public"."installed_integrations"."instance_color" IS 'Cor hexadecimal para identificação visual da instância na UI';



COMMENT ON COLUMN "public"."installed_integrations"."description" IS 'Descrição opcional do propósito desta instância de integração';



COMMENT ON COLUMN "public"."installed_integrations"."parent_integration_id" IS 'Links this integration (e.g. Marketplace) to a parent integration (e.g. ERP)';



COMMENT ON COLUMN "public"."installed_integrations"."is_default" IS 'True if this is the default integration for its category and functional scope';



COMMENT ON COLUMN "public"."installed_integrations"."functional_scopes" IS 'JSON list of delegated responsibilities (e.g. ["INVOICING", "ORDER_IMPORT", "STOCK_SYNC"])';



COMMENT ON COLUMN "public"."installed_integrations"."platform_slug" IS 'Referência ao slug da plataforma em integration_modules';



COMMENT ON COLUMN "public"."installed_integrations"."is_placeholder" IS 'Indica se esta integracao e um placeholder/dummy criado automaticamente para vinculos sem integracao direta.';



CREATE OR REPLACE FUNCTION "public"."find_bling_integration_by_cnpj"("p_cnpj" "text") RETURNS SETOF "public"."installed_integrations"
    LANGUAGE "sql" STABLE
    AS $$
    SELECT ii.*
      FROM installed_integrations ii
      JOIN integration_modules im ON im.id = ii.module_id
     WHERE im.tipo = 'aggregator'
       AND im.slug = 'bling'
       AND ii.is_active = true
       AND (ii.config->>'cnpj' = p_cnpj
            OR position(ii.config->>'cnpj' in p_cnpj) > 0)
     LIMIT 1;
$$;


ALTER FUNCTION "public"."find_bling_integration_by_cnpj"("p_cnpj" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."find_bling_integration_by_company_id"("p_company_id" "text") RETURNS SETOF "public"."installed_integrations"
    LANGUAGE "sql" STABLE
    AS $$
    SELECT ii.*
      FROM public.installed_integrations ii
     WHERE ii.module_id = 'bling'
       AND ii.is_active = true
       AND (
            ii.config->>'company_id' = p_company_id
            OR EXISTS (
                SELECT 1
                  FROM jsonb_array_elements_text(
                    CASE
                      WHEN jsonb_typeof(ii.config->'company_ids') = 'array'
                        THEN ii.config->'company_ids'
                      ELSE '[]'::jsonb
                    END
                  ) AS alias(company_id)
                 WHERE alias.company_id = p_company_id
            )
       )
     ORDER BY ii.is_default DESC NULLS LAST, ii.id
     LIMIT 1;
$$;


ALTER FUNCTION "public"."find_bling_integration_by_company_id"("p_company_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."find_marketplace_by_bling_loja"("p_loja_id" "text", "p_bling_integration_id" integer DEFAULT NULL::integer) RETURNS SETOF "public"."installed_integrations"
    LANGUAGE "sql" STABLE
    AS $$
    SELECT ii.*
      FROM public.channel_connections cc
      JOIN public.installed_integrations ii ON ii.id = cc.marketplace_integration_id
     WHERE cc.aggregator_store_id = p_loja_id
       AND cc.is_active = true
       AND ii.is_active = true
       AND cc.marketplace_integration_id IS NOT NULL
       AND (
            p_bling_integration_id IS NULL
            OR cc.bling_integration_id = p_bling_integration_id
       )
     ORDER BY
       CASE WHEN cc.bling_integration_id = p_bling_integration_id THEN 0 ELSE 1 END,
       cc.updated_at DESC NULLS LAST
     LIMIT 1;
$$;


ALTER FUNCTION "public"."find_marketplace_by_bling_loja"("p_loja_id" "text", "p_bling_integration_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."find_marketplace_by_bling_loja"("p_loja_id" "text", "p_bling_integration_id" integer) IS 'Resolves marketplace integration by Bling loja_id using channel_connections as source of truth (N:N model). Optional p_bling_integration_id parameter for disambiguation when same loja_id appears in multiple Bling instances.';



CREATE OR REPLACE FUNCTION "public"."find_shopee_connection"("p_bling_integration_id" bigint, "p_aggregator_store_id" "text") RETURNS TABLE("marketplace_integration_id" integer, "channel_id" integer, "shopee_config" "jsonb", "shopee_credentials" "jsonb")
    LANGUAGE "sql" STABLE
    AS $$
    SELECT cc.marketplace_integration_id,
           cc.channel_id,
           ii.config      AS shopee_config,
           ii.credentials AS shopee_credentials
      FROM channel_connections cc
      JOIN installed_integrations ii
           ON ii.id = cc.marketplace_integration_id
     WHERE cc.bling_integration_id = p_bling_integration_id
       AND cc.aggregator_store_id  = p_aggregator_store_id
       AND cc.is_active = true
     LIMIT 1;
$$;


ALTER FUNCTION "public"."find_shopee_connection"("p_bling_integration_id" bigint, "p_aggregator_store_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_atualizar_requer_revisao"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$ BEGIN NEW.requer_revisao = (NEW.pedidos_apos_edicao_qtd > 0); RETURN NEW; END; $$;


ALTER FUNCTION "public"."fn_atualizar_requer_revisao"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_canais_proximos_coleta"("p_limit" integer DEFAULT 2) RETURNS TABLE("fn_id" integer, "fn_nome" character varying, "fn_horario_coleta" "text", "fn_flex" boolean, "fn_fulfillment" boolean, "fn_color" character varying, "fn_dist_min" integer, "fn_is_proximo" boolean)
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    v_horario_atual time;
    v_horario_atual_minutos integer;
BEGIN
    -- Obter horário atual (time only)
    SELECT CURRENT_TIME INTO v_horario_atual;

    -- Converter para minutos
    v_horario_atual_minutos := EXTRACT(HOUR FROM v_horario_atual) * 60 + EXTRACT(MINUTE FROM v_horario_atual);

    RETURN QUERY
    WITH canais_com_horario AS (
        SELECT
            c.id AS c_id,
            c.nome AS c_nome,
            c.horario_coleta,
            c.flex,
            c.fulfillment,
            c.color,
            -- Calcular minutos até a coleta (CAST PARA INTEGER)
            CASE
                -- Se horário de coleta >= horário atual: mesmo dia
                WHEN EXTRACT(HOUR FROM c.horario_coleta) * 60 + EXTRACT(MINUTE FROM c.horario_coleta) >= v_horario_atual_minutos
                THEN ((EXTRACT(HOUR FROM c.horario_coleta) * 60 + EXTRACT(MINUTE FROM c.horario_coleta)) - v_horario_atual_minutos)::integer
                -- Se horário de coleta < horário atual: dia seguinte
                ELSE ((24 * 60 - v_horario_atual_minutos) + (EXTRACT(HOUR FROM c.horario_coleta) * 60 + EXTRACT(MINUTE FROM c.horario_coleta)))::integer
            END AS dist_min
        FROM
            public.canais_venda c
        WHERE
            c.ativo = true
            AND c.horario_coleta IS NOT NULL
    ),
    canais_ordenados AS (
        SELECT
            c_id,
            c_nome,
            TO_CHAR(horario_coleta, 'HH24:MI') AS horario_coleta_text,
            flex,
            fulfillment,
            color,
            dist_min,
            ROW_NUMBER() OVER (ORDER BY dist_min ASC) AS rn
        FROM
            canais_com_horario
    )
    SELECT
        c.c_id AS fn_id,
        c.c_nome AS fn_nome,
        c.horario_coleta_text AS fn_horario_coleta,
        c.flex,
        c.fulfillment,
        c.color,
        c.dist_min AS fn_dist_min,
        -- Marcar como "próximo" os N primeiros (default 2)
        (c.rn <= p_limit) AS fn_is_proximo
    FROM
        canais_ordenados c
    WHERE
        c.rn <= p_limit
    ORDER BY
        c.dist_min ASC;
END;
$$;


ALTER FUNCTION "public"."fn_canais_proximos_coleta"("p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_canais_proximos_coleta"("p_limit" integer) IS 'Retorna os canais ativos com horário de coleta mais próximo do horário atual.';



CREATE OR REPLACE FUNCTION "public"."fn_contar_pedidos_por_canal"("p_canal_venda_id" integer DEFAULT NULL::integer, "p_dias" integer DEFAULT 7, "p_has_demanda" boolean DEFAULT NULL::boolean) RETURNS TABLE("canal_venda_id" integer, "canal_venda_nome" character varying, "total_pedidos" bigint, "pedidos_sem_demanda" bigint, "pedidos_com_demanda" bigint)
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id AS canal_venda_id,
        c.nome AS canal_venda_nome,
        COUNT(p.id) AS total_pedidos,
        COUNT(DISTINCT CASE WHEN dp.pedido_id IS NULL THEN p.id END) AS pedidos_sem_demanda,
        COUNT(DISTINCT CASE WHEN dp.pedido_id IS NOT NULL THEN p.id END) AS pedidos_com_demanda
    FROM
        public.canais_venda c
    LEFT JOIN
        public.pedidos p ON p.canal_venda_id = c.id
            AND p.created_at >= (CURRENT_DATE - (p_dias || ' days')::interval)
    LEFT JOIN
        public.demandas_pedidos dp ON dp.pedido_id = p.id
    WHERE
        c.ativo = true
        AND (p_canal_venda_id IS NULL OR c.id = p_canal_venda_id)
        AND (
            p_has_demanda IS NULL OR
            (p_has_demanda = false AND dp.pedido_id IS NULL) OR
            (p_has_demanda = true AND dp.pedido_id IS NOT NULL)
        )
    GROUP BY
        c.id, c.nome
    ORDER BY
        total_pedidos DESC;
END;
$$;


ALTER FUNCTION "public"."fn_contar_pedidos_por_canal"("p_canal_venda_id" integer, "p_dias" integer, "p_has_demanda" boolean) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_contar_pedidos_por_canal"("p_canal_venda_id" integer, "p_dias" integer, "p_has_demanda" boolean) IS 'Conta pedidos por canal de venda. Usa tabela pivot demandas_pedidos.';



CREATE OR REPLACE FUNCTION "public"."fn_external_id"("p_pedido_id" integer, "p_platform" character varying DEFAULT NULL::character varying) RETURNS character varying
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id_na_plataforma
    FROM "public"."vinculos_integracao_pedido"
    WHERE pedido_id = p_pedido_id 
      AND (p_platform IS NULL OR plataforma = p_platform)
    ORDER BY 
        CASE WHEN p_platform IS NOT NULL AND plataforma = p_platform THEN 0 ELSE 1 END,
        created_at DESC
    LIMIT 1;
$$;


ALTER FUNCTION "public"."fn_external_id"("p_pedido_id" integer, "p_platform" character varying) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_external_id"("p_pedido_id" integer, "p_platform" character varying) IS 'Retorna o ID externo de um pedido na plataforma especificada.
   Substitui o campo deprecated pedidos.codigo_pedido_externo.
   Se p_platform for NULL, retorna o primeiro ID externo disponível.';



CREATE OR REPLACE FUNCTION "public"."fn_snapshot_channel_on_insert"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO ''
    AS $$
DECLARE
    v_config jsonb;
BEGIN
    SELECT cv.configuracao
      INTO v_config
      FROM public.canais_venda AS cv
     WHERE cv.id = NEW.canal_venda_id;

    NEW.channel_snapshot := v_config;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."fn_snapshot_channel_on_insert"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_sugerir_valores_demanda"("p_canal_venda_id" integer, "p_tipo_demanda" character varying DEFAULT 'PLATAFORMA'::character varying, "p_data_entrega" "date" DEFAULT NULL::"date") RETURNS TABLE("horario_coleta_sugerido" time without time zone, "modalidade_logistica_sugerida" character varying, "data_limite_execucao_sugerida" "date", "is_flex_sugerido" boolean, "fulfillment_sugerido" boolean, "prazo_dias" integer, "horario_limite" time without time zone, "regra_origem" character varying, "alertas" "jsonb")
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    v_horario_limite TIME;
    v_prioridade INTEGER;
    v_prazo_dias INTEGER;
    v_alertas JSONB := '[]'::jsonb;
BEGIN
    -- Buscar regra logística prioritária do canal
    SELECT 
        rl.horario_limite,
        rl.modalidade,
        CASE 
            WHEN rl.modalidade = 'EXPRESS' THEN 1
            WHEN rl.modalidade = 'STANDARD' THEN 2
            WHEN rl.modalidade = 'FULFILLMENT' THEN 3
            ELSE 4
        END as prioridade
    INTO 
        v_horario_limite,
        modalidade_logistica_sugerida,
        v_prioridade
    FROM "public"."regras_logisticas_canal" rl
    WHERE rl.canal_venda_id = p_canal_venda_id
    ORDER BY v_prioridade, rl.prioridade_uso
    LIMIT 1;

    -- Se encontrou regra
    IF modalidade_logistica_sugerida IS NOT NULL THEN
        horario_coleta_sugerido := v_horario_limite;
        horario_limite := v_horario_limite;
        regra_origem := 'regras_logisticas_canal';
        
        -- Calcular prazo em dias baseado na modalidade
        SELECT CASE 
            WHEN modalidade_logistica_sugerida = 'EXPRESS' THEN 1
            WHEN modalidade_logistica_sugerida = 'STANDARD' THEN 2
            WHEN modalidade_logistica_sugerida = 'FULFILLMENT' THEN 3
            ELSE 2
        END INTO v_prazo_dias;
        
        prazo_dias := v_prazo_dias;
        
        -- Calcular data limite de execução
        IF p_data_entrega IS NOT NULL THEN
            data_limite_execucao_sugerida := p_data_entrega - (v_prazo_dias || ' days')::INTERVAL;
        END IF;
        
        -- Adicionar alerta se horário for muito cedo/tarde
        IF v_horario_limite < '10:00'::time THEN
            v_alertas := v_alertas || '{"Horário de coleta muito cedo (< 10:00)"}'::jsonb;
        ELSIF v_horario_limite > '17:00'::time THEN
            v_alertas := v_alertas || '{"Horário de coleta tardio (> 17:00)"}'::jsonb;
        END IF;
    ELSE
        -- Sem regras logísticas: usar valores padrão
        horario_coleta_sugerido := '14:00'::time;
        horario_limite := '14:00'::time;
        modalidade_logistica_sugerida := 'STANDARD';
        prazo_dias := 2;
        regra_origem := 'padrao_sistema';
        v_alertas := '{"Canal sem regras logísticas definidas"}'::jsonb;
    END IF;
    
    -- Herdar flags do canal
    SELECT 
        COALESCE(cv.flex, false),
        COALESCE(cv.fulfillment, false)
    INTO 
        is_flex_sugerido,
        fulfillment_sugerido
    FROM "public"."canais_venda" cv
    WHERE cv.id = p_canal_venda_id;
    
    -- Se não encontrou canal
    IF is_flex_sugerido IS NULL THEN
        is_flex_sugerido := false;
        fulfillment_sugerido := false;
    END IF;
    
    alertas := v_alertas;
    
    RETURN QUERY SELECT 
        horario_coleta_sugerido,
        modalidade_logistica_sugerida,
        data_limite_execucao_sugerida,
        is_flex_sugerido,
        fulfillment_sugerido,
        prazo_dias,
        horario_limite,
        regra_origem,
        alertas;
END;
$$;


ALTER FUNCTION "public"."fn_sugerir_valores_demanda"("p_canal_venda_id" integer, "p_tipo_demanda" character varying, "p_data_entrega" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_sugerir_valores_demanda"("p_canal_venda_id" integer, "p_tipo_demanda" character varying, "p_data_entrega" "date") IS 'Calcula valores sugeridos para criação de demanda baseados no canal de venda.
   Retorna: horário de coleta, modalidade logística, data limite, flags e alertas.
   Usado por todas as fontes de geração de demanda (planilha, múltiplos pedidos, direta).';



CREATE OR REPLACE FUNCTION "public"."fn_validar_override_demanda"("p_campo" character varying, "p_valor_alterado" "jsonb", "p_canal_venda_id" integer) RETURNS TABLE("valid" boolean, "alertas" "jsonb", "bloqueios" "jsonb")
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    v_alertas JSONB := '[]'::jsonb;
    v_bloqueios JSONB := '[]'::jsonb;
    v_valid BOOLEAN := true;
    v_horario_limite TIME;
    v_valor_time TIME;
BEGIN
    -- Buscar horário limite do canal
    SELECT MAX(rl.horario_limite) INTO v_horario_limite
    FROM "public"."regras_logisticas_canal" rl
    WHERE rl.canal_venda_id = p_canal_venda_id
      AND rl.is_active = true;
    
    -- Validação por campo
    IF p_campo = 'horario_coleta' THEN
        -- Converter JSONB para TIME
        BEGIN
            v_valor_time := (p_valor_alterado #>> '{}')::time;
        EXCEPTION WHEN OTHERS THEN
            v_valid := false;
            v_bloqueios := v_bloqueios || '{"Formato de horário inválido"}'::jsonb;
        END;
        
        -- Verificar se está dentro do expediente
        IF v_valid AND (v_valor_time < '08:00'::time OR v_valor_time > '18:00'::time) THEN
            v_bloqueios := v_bloqueios || '{"Horário fora do expediente (08:00-18:00)"}'::jsonb;
        END IF;
        
        -- Alerta se após horário limite
        IF v_valid AND v_horario_limite IS NOT NULL AND v_valor_time > v_horario_limite THEN
            v_alertas := v_alertas || format('{"Horário após limite de coleta (%s)"}', v_horario_limite)::jsonb;
        END IF;
        
    ELSIF p_campo = 'modalidade_logistica' THEN
        -- Verificar se modalidade existe nas regras do canal
        IF NOT EXISTS (
            SELECT 1 FROM "public"."regras_logisticas_canal" rl
            WHERE rl.canal_venda_id = p_canal_venda_id
              AND rl.modalidade = (p_valor_alterado #>> '{}')
        ) THEN
            v_alertas := v_alertas || '{"Modalidade não existe nas regras do canal"}'::jsonb;
        END IF;
        
    ELSIF p_campo = 'data_limite_execucao' THEN
        -- Verificar se data não é muito próxima
        IF (p_valor_alterado #>> '{}')::date < CURRENT_DATE THEN
            v_bloqueios := v_bloqueios || '{"Data limite não pode ser no passado"}'::jsonb;
        END IF;
        
    ELSIF p_campo IN ('is_flex', 'fulfillment') THEN
        -- Flags podem ser alteradas livremente, apenas alerta
        v_alertas := v_alertas || '{"Alteração pode impactar logística"}'::jsonb;
    END IF;
    
    valid := v_valid AND jsonb_array_length(v_bloqueios) = 0;
    alertas := v_alertas;
    bloqueios := v_bloqueios;
    
    RETURN QUERY SELECT valid, alertas, bloqueios;
END;
$$;


ALTER FUNCTION "public"."fn_validar_override_demanda"("p_campo" character varying, "p_valor_alterado" "jsonb", "p_canal_venda_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_validar_override_demanda"("p_campo" character varying, "p_valor_alterado" "jsonb", "p_canal_venda_id" integer) IS 'Valida se um override de campo é compatível com as regras do canal.
   Retorna: valid (boolean), alertas (JSONB), bloqueios (JSONB).';



CREATE OR REPLACE FUNCTION "public"."get_alertas_producao"() RETURNS TABLE("tipo_alerta" "text", "severidade" "text", "titulo" "text", "mensagem" "text", "quantidade" integer, "detalhes" "jsonb", "created_at" timestamp with time zone)
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    -- Alerta 1: Pedidos Órfãos (sem demanda há mais de 24h)
    RETURN QUERY
    SELECT 
        'PEDIDOS_ORFAOS'::TEXT as tipo_alerta,
        CASE 
            WHEN COUNT(*) > 20 THEN 'alta'
            WHEN COUNT(*) > 10 THEN 'media'
            ELSE 'baixa'
        END::TEXT as severidade,
        'Pedidos sem Demanda Vinculada'::TEXT as titulo,
        FORMAT('%s pedidos estão sem demanda vinculada há mais de 24 horas', COUNT(*))::TEXT as mensagem,
        COUNT(*)::INTEGER as quantidade,
        jsonb_build_object(
            'pedidos', (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'pedido_id', p.id,
                        'numero_pedido', p.numero_pedido,
                        'codigo_externo', p.codigo_pedido_externo,
                        'cliente', p.cliente_nome,
                        'data_venda', p.data_venda,
                        'horas_sem_demanda', EXTRACT(EPOCH FROM (NOW() - p.data_venda)) / 3600
                    )
                )
                FROM pedidos p
                WHERE p.situacao_pedido_id IN (1, 2) -- Pendente ou Pago
                AND NOT EXISTS (SELECT 1 FROM demandas_producao dp WHERE dp.pedido_id = p.id)
                AND p.data_venda < NOW() - INTERVAL '24 hours'
                ORDER BY p.data_venda ASC
                LIMIT 10
            )
        )::JSONB as detalhes,
        NOW()::TIMESTAMPTZ as created_at
    FROM pedidos p
    WHERE p.situacao_pedido_id IN (1, 2)
    AND NOT EXISTS (SELECT 1 FROM demandas_producao dp WHERE dp.pedido_id = p.id)
    AND p.data_venda < NOW() - INTERVAL '24 hours'
    
    UNION ALL
    
    -- Alerta 2: Demandas Atrasadas
    SELECT 
        'DEMANDAS_ATRASADAS'::TEXT as tipo_alerta,
        CASE 
            WHEN COUNT(*) > 10 THEN 'alta'
            WHEN COUNT(*) > 5 THEN 'media'
            ELSE 'baixa'
        END::TEXT as severidade,
        'Demandas Atrasadas'::TEXT as titulo,
        FORMAT('%s demandas estão com data de entrega vencida e não concluídas', COUNT(*))::TEXT as mensagem,
        COUNT(*)::INTEGER as quantidade,
        jsonb_build_object(
            'demandas', (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'demanda_id', dp.demanda_id,
                        'descricao', dp.descricao,
                        'data_entrega', dp.data_entrega,
                        'dias_atraso', EXTRACT(DAY FROM (NOW() - dp.data_entrega)),
                        'status', dp.status,
                        'progresso', COALESCE(
                            (SELECT ROUND((SUM(COALESCE(id.finalizados_qtd, 0)) / NULLIF(SUM(id.quantidade, 0), 0)) * 100)
                             FROM itens_demanda id WHERE id.demanda_id = dp.id), 0
                        )
                    )
                )
                FROM demandas_producao dp
                WHERE dp.data_entrega < CURRENT_DATE
                AND dp.status NOT IN ('CONCLUIDO', 'CANCELADO')
                ORDER BY dp.data_entrega ASC
                LIMIT 10
            )
        )::JSONB as detalhes,
        NOW()::TIMESTAMPTZ as created_at
    FROM demandas_producao dp
    WHERE dp.data_entrega < CURRENT_DATE
    AND dp.status NOT IN ('CONCLUIDO', 'CANCELADO')
    
    UNION ALL
    
    -- Alerta 3: Pedidos FLEX sem atenção especial
    SELECT 
        'FLEX_URGENTE'::TEXT as tipo_alerta,
        'media'::TEXT as severidade,
        'Pedidos FLEX Próximos do Prazo'::TEXT as titulo,
        FORMAT('%s pedidos FLEX estão próximos do prazo de entrega', COUNT(*))::TEXT as mensagem,
        COUNT(*)::INTEGER as quantidade,
        jsonb_build_object(
            'pedidos_flex', (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'pedido_id', p.id,
                        'numero_pedido', p.numero_pedido,
                        'cliente', p.cliente_nome,
                        'data_limite_envio', p.data_limite_envio,
                        'horas_restantes', EXTRACT(EPOCH FROM (p.data_limite_envio - NOW())) / 3600
                    )
                )
                FROM pedidos p
                WHERE p.is_flex = TRUE
                AND p.situacao_pedido_id IN (1, 2)
                AND p.data_limite_envio BETWEEN NOW() AND NOW() + INTERVAL '48 hours'
                ORDER BY p.data_limite_envio ASC
                LIMIT 10
            )
        )::JSONB as detalhes,
        NOW()::TIMESTAMPTZ as created_at
    FROM pedidos p
    WHERE p.is_flex = TRUE
    AND p.situacao_pedido_id IN (1, 2)
    AND p.data_limite_envio BETWEEN NOW() AND NOW() + INTERVAL '48 hours'
    
    UNION ALL
    
    -- Alerta 4: Demandas sem alocação de estoque
    SELECT 
        'ESTOQUE_INSUFICIENTE'::TEXT as tipo_alerta,
        'alta'::TEXT as severidade,
        'Demandas com Estoque Insuficiente'::TEXT as titulo,
        FORMAT('%s demandas podem ter problemas de estoque', COUNT(*))::TEXT as mensagem,
        COUNT(*)::INTEGER as quantidade,
        jsonb_build_object(
            'demandas_estoque', (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'demanda_id', dp.demanda_id,
                        'descricao', dp.descricao,
                        'itens_sem_estoque', (
                            SELECT COUNT(*)
                            FROM itens_demanda id
                            WHERE id.demanda_id = dp.id
                            AND id.quantidade > (
                                SELECT COALESCE(SUM(ea.quantidade), 0)
                                FROM estoque_atual ea
                                WHERE ea.produto_id = id.produto_id
                            )
                        )
                    )
                )
                FROM demandas_producao dp
                WHERE dp.status IN ('AGUARDANDO', 'EM_PRODUCAO')
                ORDER BY dp.data_entrega ASC
                LIMIT 10
            )
        )::JSONB as detalhes,
        NOW()::TIMESTAMPTZ as created_at
    FROM demandas_producao dp
    WHERE dp.status IN ('AGUARDANDO', 'EM_PRODUCAO')
    AND EXISTS (
        SELECT 1
        FROM itens_demanda id
        WHERE id.demanda_id = dp.id
        AND id.quantidade > (
            SELECT COALESCE(SUM(ea.quantidade), 0)
            FROM estoque_atual ea
            WHERE ea.produto_id = id.produto_id
        )
    )
    LIMIT 1;
    
END;
$$;


ALTER FUNCTION "public"."get_alertas_producao"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_demandas_ativas_com_pedido"("p_pedido_externo_id" "text") RETURNS TABLE("demanda_id" "text", "demanda_internal_id" integer, "descricao" "text", "status" "text", "data_entrega" "date", "data_criacao" timestamp with time zone, "canal_venda_id" integer, "is_flex" boolean)
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        dp.demanda_id::TEXT,
        dp.id::INTEGER as demanda_internal_id,
        dp.descricao,
        dp.status,
        dp.data_entrega,
        dp.created_at as data_criacao,
        dp.canal_venda_id,
        dp.is_flex
    FROM demandas_producao dp
    INNER JOIN itens_demanda id ON dp.id = id.demanda_id
    INNER JOIN demandas_item_origem dio ON id.id = dio.demanda_item_id
    WHERE 
        dio.pedido_externo_id = p_pedido_externo_id
        AND dp.status NOT IN ('CONCLUIDO', 'CANCELADO')
    ORDER BY dp.data_entrega ASC;
END;
$$;


ALTER FUNCTION "public"."get_demandas_ativas_com_pedido"("p_pedido_externo_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_demandas_ativas_com_pedido"("p_pedido_externo_id" "text") IS 'Busca demandas ativas que contêm um pedido específico pelo ID externo';



CREATE OR REPLACE FUNCTION "public"."get_demandas_do_pedido"("p_pedido_id" bigint) RETURNS "jsonb"
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'demanda_id', dp.id,
                    'demanda_uuid', dp.demanda_id,
                    'descricao', dp.descricao,
                    'status', dp.status,
                    'tipo_demanda', dp.tipo_demanda,
                    'quantidade', dp.quantidade,
                    'data_entrega', dp.data_entrega,
                    'prioridade', dp.prioridade,
                    'created_at', dp.created_at
                )
            ),
            '[]'::jsonb
        )
        FROM public.demandas_pedidos dp_rel
        JOIN public.demandas_producao dp ON dp_rel.demanda_id = dp.id
        WHERE dp_rel.pedido_id = p_pedido_id
          AND dp.status != 'CANCELADO'
    );
END;
$$;


ALTER FUNCTION "public"."get_demandas_do_pedido"("p_pedido_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_demandas_por_pedido_externo"("p_pedido_externo_id" "text") RETURNS TABLE("demanda_id" "text", "descricao" "text", "status" "text", "data_entrega" "date", "horario_coleta" time without time zone, "tipo_demanda" "text", "is_flex" boolean, "created_at" timestamp with time zone, "canal_venda" "jsonb", "itens" "jsonb")
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        dp.demanda_id::TEXT,
        dp.descricao,
        dp.status,
        dp.data_entrega,
        dp.horario_coleta,
        dp.tipo_demanda,
        dp.is_flex,
        dp.created_at,
        row_to_json(cv)::JSONB as canal_venda,
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'id', id.id,
                    'quantidade', id.quantidade,
                    'descricao', id.descricao,
                    'sku', id.sku,
                    'finalizados_qtd', id.finalizados_qtd,
                    'origens', (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'pedido_externo_id', dio.pedido_externo_id,
                                'plataforma', dio.plataforma,
                                'quantidade_atendida', dio.quantidade_atendida
                            )
                        )
                        FROM demandas_item_origem dio
                        WHERE dio.demanda_item_id = id.id
                    )
                )
            )
            FROM itens_demanda id
            WHERE id.demanda_id = dp.id
        ) as itens
    FROM demandas_producao dp
    INNER JOIN itens_demanda id ON dp.id = id.demanda_id
    INNER JOIN demandas_item_origem dio ON id.id = dio.demanda_item_id
    LEFT JOIN canais_venda cv ON dp.canal_venda_id = cv.id
    WHERE dio.pedido_externo_id = p_pedido_externo_id
    ORDER BY dp.created_at DESC;
END;
$$;


ALTER FUNCTION "public"."get_demandas_por_pedido_externo"("p_pedido_externo_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_ingest_archive_batch"("p_dataset" "text", "p_before" timestamp with time zone, "p_limit" integer DEFAULT 1000) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
  result jsonb;
  batch_limit integer := LEAST(GREATEST(COALESCE(p_limit, 1000), 1), 5000);
BEGIN
  CASE p_dataset
    WHEN 'webhook_payloads' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.received_at, row_data.id), '[]'::jsonb)
      INTO result
      FROM (
        SELECT * FROM public.webhook_events
        WHERE received_at < p_before
          AND raw_archived_at IS NULL
          AND (raw_body IS NOT NULL OR raw_payload <> '{}'::jsonb)
          AND last_status NOT IN ('pending', 'accepted', 'pending_retry', 'processing', 'manual_intervention')
        ORDER BY received_at, id LIMIT batch_limit
      ) row_data;
    WHEN 'shopee_chat_payloads' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.event_time, row_data.id), '[]'::jsonb)
      INTO result
      FROM (
        SELECT message.*,
               COALESCE(message.received_at, message.created_timestamp,
                        message.created_at AT TIME ZONE 'UTC') AS event_time
        FROM public.mensagem_chat_shopee message
        WHERE COALESCE(message.received_at, message.created_timestamp,
                       message.created_at AT TIME ZONE 'UTC') < p_before
          AND message.raw_archived_at IS NULL
          AND (message.raw_json IS NOT NULL OR message.raw_payload IS NOT NULL)
        ORDER BY event_time, message.id LIMIT batch_limit
      ) row_data;
    WHEN 'webhook_event_attempts' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result
      FROM (
        SELECT attempt.* FROM public.webhook_event_attempts attempt
        JOIN public.webhook_events event ON event.id = attempt.webhook_event_id
        WHERE attempt.created_at < p_before
          AND event.last_status NOT IN ('pending', 'accepted', 'pending_retry', 'processing', 'manual_intervention')
        ORDER BY attempt.created_at, attempt.id LIMIT batch_limit
      ) row_data;
    WHEN 'task_execution_logs' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result FROM (
        SELECT * FROM public.task_execution_logs
        WHERE created_at < p_before ORDER BY created_at, id LIMIT batch_limit
      ) row_data;
    WHEN 'pedido_ingest_log' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result FROM (
        SELECT * FROM public.pedido_ingest_log
        WHERE created_at < p_before ORDER BY created_at, id LIMIT batch_limit
      ) row_data;
    WHEN 'integration_refresh_logs' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result FROM (
        SELECT * FROM public.integration_refresh_logs
        WHERE (lower(status) IN ('success', 'completed', 'ok') AND created_at < p_before)
           OR (lower(status) NOT IN ('success', 'completed', 'ok') AND created_at < p_before - interval '23 days')
        ORDER BY created_at, id LIMIT batch_limit
      ) row_data;
    ELSE
      RAISE EXCEPTION 'unsupported archive dataset: %', p_dataset;
  END CASE;
  RETURN result;
END;
$$;


ALTER FUNCTION "public"."get_ingest_archive_batch"("p_dataset" "text", "p_before" timestamp with time zone, "p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_ledger_por_item_demanda"("p_item_id" integer, "p_demanda_id" integer) RETURNS TABLE("id" "uuid", "estagio" character varying, "tipo_movimentacao" character varying, "produto_id" integer, "produto_nome" character varying, "quantidade" numeric, "saldo_acumulado" numeric, "correlation_id" character varying, "created_at" timestamp with time zone)
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT 
        dep.id,
        dep.estagio,
        dep.tipo_movimentacao,
        dep.produto_id,
        p.nome as produto_nome,
        dep.quantidade,
        dep.saldo_acumulado,
        dep.correlation_id,
        dep.created_at
    FROM public.demanda_estoque_processado dep
    LEFT JOIN public.produtos p ON dep.produto_id = p.id
    WHERE dep.item_id = p_item_id 
      AND dep.demanda_id = p_demanda_id
    ORDER BY dep.created_at ASC;
END;
$$;


ALTER FUNCTION "public"."get_ledger_por_item_demanda"("p_item_id" integer, "p_demanda_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_ledger_por_item_demanda"("p_item_id" integer, "p_demanda_id" integer) IS 'Retorna todo o histórico de movimentações de estoque para um item específico de uma demanda.';



CREATE OR REPLACE FUNCTION "public"."get_pedidos_com_filtros_avancados"("p_situacao_pedido_id" integer DEFAULT NULL::integer, "p_canal_venda_id" integer DEFAULT NULL::integer, "p_has_demanda" boolean DEFAULT NULL::boolean, "p_delivery_start_date" "text" DEFAULT NULL::"text", "p_delivery_end_date" "text" DEFAULT NULL::"text", "p_search_term" "text" DEFAULT NULL::"text", "p_limit" integer DEFAULT 50, "p_offset" integer DEFAULT 0) RETURNS TABLE("id" bigint, "numero_pedido" character varying, "codigo_pedido_externo" character varying, "data_venda" timestamp with time zone, "cliente_nome" character varying, "cliente_documento" character varying, "canal_venda_id" integer, "canal_venda_nome" character varying, "situacao_pedido_id" integer, "total_pedido" numeric, "tem_demanda" boolean, "origem" character varying, "created_at" timestamp with time zone)
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.id,
        p.numero_pedido,
        p.codigo_pedido_externo,
        p.data_venda,
        p.cliente_nome,
        p.cliente_documento,
        p.canal_venda_id,
        cv.nome AS canal_venda_nome,
        p.situacao_pedido_id,
        p.total_pedido,
        EXISTS (
            SELECT 1 FROM demandas_pedidos dp 
            WHERE dp.pedido_id = p.id
        ) AS tem_demanda,
        p.origem,
        p.created_at
    FROM pedidos p
    LEFT JOIN canais_venda cv ON p.canal_venda_id = cv.id
    WHERE 
        (p_situacao_pedido_id IS NULL OR p.situacao_pedido_id = p_situacao_pedido_id)
        AND (p_canal_venda_id IS NULL OR p.canal_venda_id = p_canal_venda_id)
        AND (
            p_has_demanda IS NULL OR
            (p_has_demanda = TRUE AND EXISTS (
                SELECT 1 FROM demandas_pedidos dp WHERE dp.pedido_id = p.id
            )) OR
            (p_has_demanda = FALSE AND NOT EXISTS (
                SELECT 1 FROM demandas_pedidos dp WHERE dp.pedido_id = p.id
            ))
        )
        AND (p_delivery_start_date IS NULL OR p.data_venda >= p_delivery_start_date::TIMESTAMPTZ)
        AND (p_delivery_end_date IS NULL OR p.data_venda <= p_delivery_end_date::TIMESTAMPTZ)
        AND (p_search_term IS NULL OR p_search_term = '' OR 
            p.numero_pedido ILIKE '%' || p_search_term || '%' OR
            p.cliente_nome ILIKE '%' || p_search_term || '%' OR
            p.codigo_pedido_externo ILIKE '%' || p_search_term || '%' OR
            p.cliente_documento ILIKE '%' || p_search_term || '%'
        )
    ORDER BY p.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;


ALTER FUNCTION "public"."get_pedidos_com_filtros_avancados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_pedidos_contexto_consolidacao"("p_filtro_contexto" "text" DEFAULT NULL::"text", "p_canal_venda_id" integer DEFAULT NULL::integer, "p_data_limite_inicio" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_data_limite_fim" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_limit" integer DEFAULT 50) RETURNS TABLE("pedido_id" integer, "numero_pedido" character varying, "codigo_pedido_externo" character varying, "cliente_nome" character varying, "cliente_documento" character varying, "canal_venda_id" integer, "canal_venda_nome" character varying, "data_limite_envio" timestamp with time zone, "is_flex" boolean, "total_pedido" numeric, "qtd_itens" integer, "skus" "text", "has_demanda" boolean, "grupo_consolidacao" "text")
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.id::INTEGER as pedido_id,
        p.numero_pedido::VARCHAR,
        p.codigo_pedido_externo::VARCHAR,
        p.cliente_nome::VARCHAR,
        p.cliente_documento::VARCHAR,
        p.canal_venda_id::INTEGER,
        cv.nome::VARCHAR as canal_venda_nome,
        p.data_limite_envio::TIMESTAMPTZ,
        p.is_flex::BOOLEAN,
        p.total_pedido::NUMERIC,
        COUNT(ip.id)::INTEGER as qtd_itens,
        STRING_AGG(DISTINCT ip.sku_externo, ', ')::TEXT as skus,
        (EXISTS (SELECT 1 FROM demandas_producao dp WHERE dp.pedido_id = p.id))::BOOLEAN as has_demanda,
        CASE 
            WHEN p_filtro_contexto = 'mesmo_prazo' THEN TO_CHAR(p.data_limite_envio, 'YYYY-MM-DD')
            WHEN p_filtro_contexto = 'mesmo_canal' THEN 'canal_' || p.canal_venda_id::TEXT
            WHEN p_filtro_contexto = 'itens_similares' THEN (
                SELECT STRING_AGG(sku_externo, '_') 
                FROM (SELECT DISTINCT sku_externo FROM itens_pedido WHERE pedido_id = p.id ORDER BY sku_externo LIMIT 3) sub
            )
            ELSE 'todos'
        END as grupo_consolidacao
    FROM pedidos p
    INNER JOIN itens_pedido ip ON p.id = ip.pedido_id
    LEFT JOIN canais_venda cv ON p.canal_venda_id = cv.id
    WHERE 
        p.situacao_pedido_id IN (1, 2) -- Pendente ou Pago
        AND NOT EXISTS (SELECT 1 FROM demandas_producao dp WHERE dp.pedido_id = p.id)
        AND (p_canal_venda_id IS NULL OR p.canal_venda_id = p_canal_venda_id)
        AND (
            p_data_limite_inicio IS NULL 
            OR (p.data_limite_envio >= p_data_limite_inicio AND p.data_limite_envio <= p_data_limite_fim)
        )
    GROUP BY 
        p.id, p.numero_pedido, p.codigo_pedido_externo, p.cliente_nome,
        p.cliente_documento, p.canal_venda_id, cv.nome, p.data_limite_envio,
        p.is_flex, p.total_pedido
    HAVING 
        -- Para filtro de itens similares, apenas pedidos com mais de 1 item
        p_filtro_contexto != 'itens_similares' OR COUNT(ip.id) > 0
    ORDER BY 
        p.data_limite_envio ASC,
        p.canal_venda_id,
        p.numero_pedido
    LIMIT p_limit;
END;
$$;


ALTER FUNCTION "public"."get_pedidos_contexto_consolidacao"("p_filtro_contexto" "text", "p_canal_venda_id" integer, "p_data_limite_inicio" timestamp with time zone, "p_data_limite_fim" timestamp with time zone, "p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_pedidos_origem_options"() RETURNS TABLE("key" "text", "nome" "text", "tipo" "text", "id" integer, "loja_id" "text", "total" bigint)
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    RETURN QUERY
    WITH normalized_orders AS (
        -- Mapeia cada pedido para um identificador de loja único (loja_id)
        -- Prioriza dados da tabela pedidos_bling (que contém o shop_id/loja_id)
        SELECT
            p.id,
            COALESCE(pb.loja_id::TEXT, 'unknown') as target_loja_id
        FROM public.pedidos p
        LEFT JOIN public.pedidos_bling pb ON pb.id = p.pedido_bling_id
    ),
    loja_metadata AS (
        -- Busca nome da instância/conexão para este loja_id
        SELECT 
            aggregator_store_id as target_loja_id,
            MAX(aggregator_store_name) as store_name
        FROM public.channel_connections
        WHERE is_active = true
        GROUP BY aggregator_store_id
    )
    SELECT
        ('loja:' || n.target_loja_id)::TEXT as key,
        COALESCE(lm.store_name, 'Loja ' || n.target_loja_id)::TEXT as nome,
        'bling_loja'::TEXT as tipo,
        NULL::INTEGER as id,
        n.target_loja_id::TEXT as loja_id,
        COUNT(n.id)::BIGINT as total
    FROM normalized_orders n
    LEFT JOIN loja_metadata lm ON lm.target_loja_id = n.target_loja_id
    WHERE n.target_loja_id != 'unknown'
    GROUP BY n.target_loja_id, lm.store_name
    HAVING COUNT(n.id) > 0
    ORDER BY total DESC, nome;
END;
$$;


ALTER FUNCTION "public"."get_pedidos_origem_options"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_pedidos_origem_options"() IS 'Retorna origens distintas para filtro de pedidos usando canal, marketplace e loja Bling.';



CREATE OR REPLACE FUNCTION "public"."pedido_tem_demanda"("p_pedido_id" bigint) RETURNS boolean
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 
        FROM public.demandas_pedidos dp_rel
        JOIN public.demandas_producao dp ON dp_rel.demanda_id = dp.id
        WHERE dp_rel.pedido_id = p_pedido_id 
          AND dp.status != 'CANCELADO'
    );
END;
$$;


ALTER FUNCTION "public"."pedido_tem_demanda"("p_pedido_id" bigint) OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."canais_venda" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "plataforma_id" integer,
    "descricao" "text",
    "configuracao" "jsonb",
    "ativo" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "slug" character varying(100),
    "conta_bling_id" character varying(255),
    "horario_coleta" time without time zone,
    "flex" boolean DEFAULT false,
    "fulfillment" boolean DEFAULT false,
    "color" character varying(7) DEFAULT '#007bff'::character varying,
    "bling_loja_id_principal" bigint,
    "integration_id_principal" integer
);


ALTER TABLE "public"."canais_venda" OWNER TO "postgres";


COMMENT ON COLUMN "public"."canais_venda"."slug" IS 'URL-friendly identifier';



COMMENT ON COLUMN "public"."canais_venda"."conta_bling_id" IS 'DEPRECATED: usar channel_connections.aggregator_store_id. Será removido na Fase 6.';



COMMENT ON COLUMN "public"."canais_venda"."horario_coleta" IS 'Fonte primária de horário de coleta.
   Demandas herdam este valor no momento da criação e não são sincronizadas retroativamente.';



COMMENT ON COLUMN "public"."canais_venda"."flex" IS 'Indica se o canal suporta entrega flexível/urgente (Entrega Rápida Shopee).
   Pedidos herdam este valor via trigger no momento da criação.';



COMMENT ON COLUMN "public"."canais_venda"."fulfillment" IS 'Indica se o canal usa serviço de fulfillment externo.
   Demandas herdam este valor no momento da criação.';



COMMENT ON COLUMN "public"."canais_venda"."color" IS 'Color for UI';



COMMENT ON COLUMN "public"."canais_venda"."bling_loja_id_principal" IS 'DEPRECATED: usar channel_connections.aggregator_store_id. Será removido na Fase 6.';



COMMENT ON COLUMN "public"."canais_venda"."integration_id_principal" IS 'DEPRECATED: usar channel_connections.integration_id. Será removido na Fase 6.';



CREATE TABLE IF NOT EXISTS "public"."itens_pedido" (
    "id" integer NOT NULL,
    "pedido_id" integer,
    "produto_id" integer,
    "sku_externo" character varying(100),
    "descricao" character varying(500),
    "quantidade" numeric(10,4),
    "preco_unitario" numeric(15,2),
    "subtotal" numeric(15,2),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "personalizado" boolean DEFAULT false,
    "titulo_anuncio" "text",
    "variacao_externa" "text",
    "item_externo_id" "text",
    "variacao_externa_id" "text"
);


ALTER TABLE "public"."itens_pedido" OWNER TO "postgres";


COMMENT ON COLUMN "public"."itens_pedido"."titulo_anuncio" IS 'Titulo do anuncio na origem (Shopee raw.item_name, ML raw.item.title). Primeiro nivel da chave de consolidacao do legado.';



COMMENT ON COLUMN "public"."itens_pedido"."variacao_externa" IS 'Nome da variacao na origem (Shopee raw.model_name, ML variation_attributes). NULL quando o anuncio nao tem variacao — a consolidacao trata como "-", igual ao fillna do legado.';



COMMENT ON COLUMN "public"."itens_pedido"."item_externo_id" IS 'ID do anuncio na origem (Shopee item_id, ML item.id). Vai para demandas_item_origem.';



COMMENT ON COLUMN "public"."itens_pedido"."variacao_externa_id" IS 'ID da variacao na origem (Shopee model_id, ML variation_id).';



CREATE TABLE IF NOT EXISTS "public"."pedidos" (
    "id" integer NOT NULL,
    "uuid_pedido" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "numero_pedido" character varying(50) NOT NULL,
    "codigo_pedido_externo" character varying(100) NOT NULL,
    "origem" character varying(50) NOT NULL,
    "informacoes_cliente" "jsonb" NOT NULL,
    "situacao_pedido_id" integer,
    "total_pedido" numeric(15,2),
    "moeda" character varying(10) DEFAULT 'BRL'::character varying,
    "data_venda" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "cliente_nome" character varying(255),
    "cliente_documento" character varying(20),
    "canal_venda_id" integer,
    "cliente_telefone" character varying(50),
    "cliente_email" character varying(255),
    "is_flex" boolean DEFAULT false,
    "data_limite_envio" timestamp with time zone,
    "servico_logistico" character varying(255),
    "payload_canonico" "jsonb" DEFAULT '{}'::"jsonb",
    "channel_snapshot" "jsonb" DEFAULT '{}'::"jsonb",
    "personalizado" boolean DEFAULT false,
    "buyer_username" character varying(255),
    "marketplace_order_id" character varying(255),
    "shipping_carrier" character varying(255),
    "contact_marketplace_id" character varying(255),
    "message_to_seller" "text",
    "pedido_bling_id" bigint,
    "pedido_shopee_id" bigint,
    "modalidade_logistica" "text",
    "marketplace_integration_id" integer,
    "status_original" "text",
    "pedido_mercadolivre_id" integer,
    "is_fulfillment" boolean DEFAULT false,
    "ingest_source" character varying(50),
    "data_compra_marketplace" timestamp with time zone,
    "data_pagamento_marketplace" timestamp with time zone,
    "data_coleta" timestamp with time zone,
    "data_envio_marketplace" timestamp with time zone,
    "regra_logistica_integracao_id" bigint,
    "marketplace_module_id" "text",
    "erp_integration_id" integer,
    "erp_store_id" character varying(100),
    "erp_order_id" bigint,
    "erp_order_number" character varying(100),
    "marketplace_order_status" "text",
    "marketplace_payment_status" "text",
    "marketplace_shipping_status" "text",
    "marketplace_shipping_substatus" "text",
    "marketplace_lifecycle_stage" "text",
    "marketplace_status_updated_at" timestamp with time zone,
    "buyer_user_id" bigint,
    "modalidade_logistica_id" integer,
    "modalidade_regra_id" integer,
    "metodo_envio_chave" "text",
    "metodo_envio_rotulo" "text",
    "modalidade_classificada_em" timestamp with time zone,
    "compromisso_logistico_em" timestamp with time zone,
    "despachado_em" timestamp with time zone,
    "pack_id" "text",
    "ingest_origin_mode" "text"
);


ALTER TABLE "public"."pedidos" OWNER TO "postgres";


COMMENT ON COLUMN "public"."pedidos"."codigo_pedido_externo" IS 'DEPRECATED: usar vinculos_integracao_pedido ou função fn_external_id().
   Será removido na Fase 6 após validação.';



COMMENT ON COLUMN "public"."pedidos"."canal_venda_id" IS 'Referência ao canal de venda de origem para roteamento e relatórios.';



COMMENT ON COLUMN "public"."pedidos"."is_flex" IS 'DEPRECATED: derivado de modalidade_logistica_id pelo trigger tg_pedidos_sync_is_flex. Nao escrever diretamente. Nao usar como criterio de agrupamento em codigo novo.';



COMMENT ON COLUMN "public"."pedidos"."payload_canonico" IS 'Dados do pedido normalizados seguindo o modelo canônico (Customer, Shipping, Payments, Items).';



COMMENT ON COLUMN "public"."pedidos"."channel_snapshot" IS 'Snapshot do estado do canal no momento da criação do pedido.
   Armazena: { flex, fulfillment, horario_coleta, color, canal_nome }.
   Usado para auditoria e para garantir consistência histórica.';



COMMENT ON COLUMN "public"."pedidos"."buyer_username" IS 'Nome de usuário do marketplace (Shopee, ML, etc)';



COMMENT ON COLUMN "public"."pedidos"."marketplace_order_id" IS 'ID do pedido no marketplace externo';



COMMENT ON COLUMN "public"."pedidos"."shipping_carrier" IS 'Serviço logístico do marketplace (ex: Entrega Rápida)';



COMMENT ON COLUMN "public"."pedidos"."contact_marketplace_id" IS 'ID de contato no marketplace';



COMMENT ON COLUMN "public"."pedidos"."message_to_seller" IS 'Mensagem do comprador ao vendedor (Shopee)';



COMMENT ON COLUMN "public"."pedidos"."modalidade_logistica" IS 'Projecao legada de modalidade_logistica_id, mantida por trigger. Nao escrever direto: a fonte de verdade e a FK.';



COMMENT ON COLUMN "public"."pedidos"."data_compra_marketplace" IS 'Data/hora em que o pedido foi criado/comprado no marketplace.';



COMMENT ON COLUMN "public"."pedidos"."data_pagamento_marketplace" IS 'Data/hora do pagamento aprovado no marketplace; usada contra a hora de corte logistica.';



COMMENT ON COLUMN "public"."pedidos"."data_coleta" IS 'Data/hora prevista de coleta pela transportadora na empresa ou entrega no ponto de coleta.';



COMMENT ON COLUMN "public"."pedidos"."data_envio_marketplace" IS 'Data/hora real de envio/bipagem no sistema do marketplace.';



COMMENT ON COLUMN "public"."pedidos"."regra_logistica_integracao_id" IS 'Regra logistica por integracao usada para calcular data_coleta.';



COMMENT ON COLUMN "public"."pedidos"."buyer_user_id" IS 'Shopee buyer_user_id usado para escopo exato do Webchat; username permanece fallback.';



COMMENT ON COLUMN "public"."pedidos"."modalidade_logistica_id" IS 'NULL = nao classificado. Nunca receber default: prazo desconhecido e a hipotese mais perigosa, pode ser um Turbo com 40 minutos correndo.';



COMMENT ON COLUMN "public"."pedidos"."modalidade_regra_id" IS 'Regra que classificou o pedido. Explicabilidade: sem isso, "por que esse pedido caiu em Comum" vira investigacao manual em platform_fields.';



COMMENT ON COLUMN "public"."pedidos"."metodo_envio_chave" IS 'Identificador estavel do metodo de envio na origem (Shopee: logistics_channel_id). Base da classificacao e do agrupamento.';



COMMENT ON COLUMN "public"."pedidos"."metodo_envio_rotulo" IS 'Rotulo de exibicao do metodo de envio (Shopee: shipping_carrier). Exibicao e alerta apenas, nunca classificacao.';



COMMENT ON COLUMN "public"."pedidos"."compromisso_logistico_em" IS 'Instante do compromisso com a origem. FIXO: data operacional + corte. RELATIVO: data_venda + offset_etiqueta_min. Nao classificado: data_venda (ordena no topo). Ordenacao canonica unica do sistema.';



COMMENT ON COLUMN "public"."pedidos"."despachado_em" IS 'Preenchido na publicacao da demanda, na mesma transacao. Predicado dos indices parciais da arvore.';



COMMENT ON COLUMN "public"."pedidos"."pack_id" IS 'Identificador do pacote na origem (ML pack_id). Pedidos com o mesmo pack_id vao na mesma caixa e compartilham um unico pedido no ERP.';



COMMENT ON COLUMN "public"."pedidos"."ingest_origin_mode" IS 'Modo de ingest que governa ESTE pedido, congelado na ingestao. Trocar o modo do vinculo passa a valer para pedidos novos; os em transito terminam sob a fonte que os acompanhou desde o inicio.';



CREATE TABLE IF NOT EXISTS "public"."situacoes_pedido" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "flag_reserva_estoque" boolean DEFAULT false,
    "flag_fatura" boolean DEFAULT false,
    "flag_cancelado" boolean DEFAULT false,
    "cor_status" character varying(7) DEFAULT '#007bff'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."situacoes_pedido" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_pedidos_para_consolidar" AS
 SELECT "p"."id" AS "pedido_id",
    "p"."numero_pedido",
    "p"."codigo_pedido_externo",
    "p"."origem",
    "p"."cliente_nome",
    "p"."cliente_telefone",
    "p"."is_flex",
    "p"."data_limite_envio",
    "p"."total_pedido",
    "p"."situacao_pedido_id",
    "s"."nome" AS "situacao_nome",
    "p"."canal_venda_id",
    "cv"."nome" AS "plataforma_nome",
    "p"."servico_logistico",
    ( SELECT "jsonb_agg"("jsonb_build_object"('sku_externo', "i"."sku_externo", 'descricao', "i"."descricao", 'quantidade', "i"."quantidade")) AS "jsonb_agg"
           FROM "public"."itens_pedido" "i"
          WHERE ("i"."pedido_id" = "p"."id")) AS "itens",
    "public"."pedido_tem_demanda"(("p"."id")::bigint) AS "has_demanda",
    "public"."get_demandas_do_pedido"(("p"."id")::bigint) AS "demandas"
   FROM (("public"."pedidos" "p"
     LEFT JOIN "public"."situacoes_pedido" "s" ON (("p"."situacao_pedido_id" = "s"."id")))
     LEFT JOIN "public"."canais_venda" "cv" ON (("p"."canal_venda_id" = "cv"."id")))
  WHERE ("p"."situacao_pedido_id" = ANY (ARRAY[1, 2]));


ALTER VIEW "public"."view_pedidos_para_consolidar" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_pedidos_para_consolidar"("p_plataforma_id" integer DEFAULT NULL::integer, "p_is_flex" boolean DEFAULT NULL::boolean, "p_data_inicio" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_data_fim" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_search" "text" DEFAULT NULL::"text") RETURNS SETOF "public"."view_pedidos_para_consolidar"
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM public.view_pedidos_para_consolidar v
    WHERE 
        (p_plataforma_id IS NULL OR v.canal_venda_id = p_plataforma_id) AND
        (p_is_flex IS NULL OR v.is_flex = p_is_flex) AND
        (p_data_inicio IS NULL OR v.data_limite_envio >= p_data_inicio) AND
        (p_data_fim IS NULL OR v.data_limite_envio <= p_data_fim) AND
        (p_search IS NULL OR 
            v.cliente_nome ILIKE '%' || p_search || '%' OR 
            v.numero_pedido ILIKE '%' || p_search || '%' OR 
            v.codigo_pedido_externo ILIKE '%' || p_search || '%'
        );
END;
$$;


ALTER FUNCTION "public"."get_pedidos_para_consolidar"("p_plataforma_id" integer, "p_is_flex" boolean, "p_data_inicio" timestamp with time zone, "p_data_fim" timestamp with time zone, "p_search" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_pedidos_por_demanda"("p_demanda_id" "text") RETURNS TABLE("pedido_externo_id" "text", "plataforma" "text", "quantidade_atendida" numeric, "item_demanda_id" integer, "sku_externo" "text", "descricao_item" "text")
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT 
        dio.pedido_externo_id::TEXT,
        dio.plataforma::TEXT,
        dio.quantidade_atendida::NUMERIC,
        dio.demanda_item_id::INTEGER,
        dio.sku_externo::TEXT,
        id.descricao::TEXT as descricao_item
    FROM demandas_item_origem dio
    INNER JOIN itens_demanda id ON dio.demanda_item_id = id.id
    WHERE id.demanda_id = (
        SELECT id FROM demandas_producao WHERE demanda_id = p_demanda_id
    )
    ORDER BY dio.pedido_externo_id, dio.plataforma;
END;
$$;


ALTER FUNCTION "public"."get_pedidos_por_demanda"("p_demanda_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_pedidos_similares"("p_pedido_id" integer, "p_limit" integer DEFAULT 10) RETURNS TABLE("pedido_id" integer, "numero_pedido" character varying, "codigo_pedido_externo" character varying, "cliente_nome" character varying, "canal_venda_id" integer, "canal_venda_nome" character varying, "data_limite_envio" timestamp with time zone, "is_flex" boolean, "itens_em_comum" integer, "skus_comuns" "text", "score_similaridade" numeric, "has_demanda" boolean)
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    v_canal_venda_id INTEGER;
    v_data_limite_envio TIMESTAMPTZ;
    v_pedido_skus TEXT[];
BEGIN
    -- Obter dados do pedido de referência
    SELECT 
        p.canal_venda_id,
        p.data_limite_envio
    INTO 
        v_canal_venda_id,
        v_data_limite_envio
    FROM pedidos p
    WHERE p.id = p_pedido_id;
    
    -- Obter SKUs do pedido de referência
    SELECT ARRAY_AGG(DISTINCT ip.sku_externo)
    INTO v_pedido_skus
    FROM itens_pedido ip
    WHERE ip.pedido_id = p_pedido_id;
    
    RETURN QUERY
    SELECT 
        p.id::INTEGER as pedido_id,
        p.numero_pedido::VARCHAR,
        p.codigo_pedido_externo::VARCHAR,
        p.cliente_nome::VARCHAR,
        p.canal_venda_id::INTEGER,
        cv.nome::VARCHAR as canal_venda_nome,
        p.data_limite_envio::TIMESTAMPTZ,
        p.is_flex::BOOLEAN,
        COUNT(DISTINCT ip.sku_externo)::INTEGER as itens_em_comum,
        STRING_AGG(DISTINCT ip.sku_externo, ', ')::TEXT as skus_comuns,
        ROUND(
            (COUNT(DISTINCT ip.sku_externo)::NUMERIC / 
            NULLIF((SELECT COUNT(DISTINCT sku_externo) FROM itens_pedido WHERE pedido_id = p_pedido_id), 0)) * 100,
            2
        ) as score_similaridade,
        (EXISTS (SELECT 1 FROM demandas_producao dp WHERE dp.pedido_id = p.id))::BOOLEAN as has_demanda
    FROM pedidos p
    INNER JOIN itens_pedido ip ON p.id = ip.pedido_id
    LEFT JOIN canais_venda cv ON p.canal_venda_id = cv.id
    WHERE 
        p.id != p_pedido_id
        AND ip.sku_externo = ANY(v_pedido_skus)
        AND p.situacao_pedido_id IN (1, 2) -- Pendente ou Pago
        AND NOT EXISTS (SELECT 1 FROM demandas_producao dp WHERE dp.pedido_id = p.id)
        -- Prazo similar (±7 dias)
        AND (
            v_data_limite_envio IS NULL 
            OR (
                p.data_limite_envio >= v_data_limite_envio - INTERVAL '7 days'
                AND p.data_limite_envio <= v_data_limite_envio + INTERVAL '7 days'
            )
        )
    GROUP BY 
        p.id, p.numero_pedido, p.codigo_pedido_externo, p.cliente_nome,
        p.canal_venda_id, cv.nome, p.data_limite_envio, p.is_flex
    ORDER BY 
        itens_em_comum DESC,
        score_similaridade DESC,
        ABS(EXTRACT(EPOCH FROM (p.data_limite_envio - v_data_limite_envio))) ASC
    LIMIT p_limit;
END;
$$;


ALTER FUNCTION "public"."get_pedidos_similares"("p_pedido_id" integer, "p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_regras_consolidacao_canal"("p_canal_venda_id" bigint, "p_modalidade" character varying DEFAULT NULL::character varying) RETURNS TABLE("canal_venda_id" bigint, "modalidade" character varying, "agrupar_por_produto" boolean, "agrupar_por_miolo" boolean, "agrupar_por_data_entrega" boolean, "janela_agrupamento_horas" integer, "comportamento_pos_edicao" character varying, "comportamento_pos_publicacao" character varying)
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY SELECT rc.canal_venda_id, rc.modalidade, rc.agrupar_por_produto, rc.agrupar_por_miolo, rc.agrupar_por_data_entrega, rc.janela_agrupamento_horas, rc.comportamento_pos_edicao, rc.comportamento_pos_publicacao
    FROM public.regras_consolidacao_canal rc WHERE rc.ativo = true AND (rc.canal_venda_id IS NULL OR rc.canal_venda_id = p_canal_venda_id) AND (rc.modalidade IS NULL OR rc.modalidade = p_modalidade)
    ORDER BY CASE WHEN rc.canal_venda_id = p_canal_venda_id THEN 0 ELSE 1 END, CASE WHEN rc.modalidade = p_modalidade THEN 0 ELSE 1 END, rc.created_at DESC LIMIT 1;
END;
$$;


ALTER FUNCTION "public"."get_regras_consolidacao_canal"("p_canal_venda_id" bigint, "p_modalidade" character varying) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."grupo_bom_do_componente"("p_componente_id" integer, "p_grupo_linha" "text" DEFAULT NULL::"text") RETURNS "text"
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public'
    AS $$
  WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
  ), comp AS (
    SELECT c.id, c.nome, c.categoria_id, cat.grupo_bom
      FROM public.produtos c
      LEFT JOIN public.categorias cat ON cat.id = c.categoria_id
     WHERE c.id = p_componente_id
  )
  SELECT coalesce(
    -- 1. a linha manda (PRODUCT_REFACTORING.md §4.5)
    nullif(btrim(p_grupo_linha), ''),
    -- 2. categoria classificada explicitamente
    comp.grupo_bom,
    -- 3. miolo pela categoria configurada
    CASE WHEN comp.categoria_id = cfg.cat_miolo THEN 'MIOLO' END,
    -- 4/5. capa x contra pelo NOME: a categoria nao distingue as duas
    CASE WHEN comp.nome ~* 'contra' THEN 'CONTRA'
         WHEN comp.nome ~* 'capa'   THEN 'CAPA' END,
    -- 6. demais grupos pela regra da categoria, exceto capa/contra (ambiguos)
    (SELECT upper(r.nome_grupo) FROM public.categoria_bom_regras r
      WHERE r.categoria_componente_id = comp.categoria_id
        AND upper(r.nome_grupo) NOT IN ('CAPA', 'CONTRA')
      ORDER BY r.ordem, r.id LIMIT 1)
  )
    FROM comp CROSS JOIN cfg;
$$;


ALTER FUNCTION "public"."grupo_bom_do_componente"("p_componente_id" integer, "p_grupo_linha" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."grupo_bom_do_componente"("p_componente_id" integer, "p_grupo_linha" "text") IS 'Grupo efetivo de uma linha de ficha tecnica. Precedencia: grupo da linha > grupo da categoria > miolo por categoria configurada > capa/contra pelo nome do componente > regra da categoria. Fonte unica: bom_efetiva_produto e produto_prontidao usam esta funcao.';



CREATE OR REPLACE FUNCTION "public"."handle_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  -- 1. Try to update 'updated_at' (New Standard)
  BEGIN
    NEW.updated_at = now();
  EXCEPTION WHEN undefined_column THEN
    -- Ignore if column doesn't exist
  END;

  -- 2. Try to update 'atualizado_em' (Legacy Fallback)
  BEGIN
    NEW.atualizado_em = now();
  EXCEPTION WHEN undefined_column THEN
    -- Ignore if column doesn't exist
  END;
  
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."incrementar_batch_ia"("p_batch_id" "uuid", "p_sucesso" integer, "p_falha" integer) RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
DECLARE v_total INT; v_proc INT;
BEGIN
    UPDATE execucoes_ai_batch
       SET processados = processados + 1,
           sucesso     = sucesso + p_sucesso,
           falha       = falha + p_falha
     WHERE id = p_batch_id
    RETURNING total, processados INTO v_total, v_proc;
    IF v_proc >= v_total THEN
        UPDATE execucoes_ai_batch
           SET status='CONCLUIDO', finalizado_em=NOW()
         WHERE id=p_batch_id;
    END IF;
END;
$$;


ALTER FUNCTION "public"."incrementar_batch_ia"("p_batch_id" "uuid", "p_sucesso" integer, "p_falha" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."item_snapshot_atributos"("p_item" "jsonb") RETURNS TABLE("sku" "text", "titulo" "text", "variacao" "text", "item_externo_id" "text", "variacao_externa_id" "text")
    LANGUAGE "sql" IMMUTABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
SELECT
    p_item->>'sku',
    coalesce(
        nullif(p_item->'raw'->>'item_name', ''),          -- Shopee
        nullif(p_item->'raw'->'item'->>'title', ''),      -- Mercado Livre
        nullif(p_item->>'name', '')                       -- canonico / demais origens
    ),
    coalesce(
        nullif(p_item->'raw'->>'model_name', ''),         -- Shopee: "CAPA 3"
        (SELECT string_agg(va->>'value_name', ' / ' ORDER BY va->>'name')
           FROM jsonb_array_elements(
                    coalesce(p_item->'raw'->'item'->'variation_attributes', '[]'::jsonb)
                ) va
          WHERE nullif(va->>'value_name','') IS NOT NULL)  -- Mercado Livre
    ),
    coalesce(
        nullif(p_item->'raw'->>'item_id', ''),
        nullif(p_item->'raw'->'item'->>'id', '')
    ),
    coalesce(
        nullif(p_item->'raw'->>'model_id', ''),
        nullif(p_item->'raw'->'item'->>'variation_id', '')
    );
$$;


ALTER FUNCTION "public"."item_snapshot_atributos"("p_item" "jsonb") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."itens_pedido_enriquecer"("p_pedido_id" integer) RETURNS integer
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_afetados integer := 0;
BEGIN
    WITH snap AS (
        SELECT DISTINCT ON (a.sku)
               a.sku, a.titulo, a.variacao, a.item_externo_id, a.variacao_externa_id
          FROM public.pedido_snapshots s
         CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.items, '[]'::jsonb)) it
         CROSS JOIN LATERAL public.item_snapshot_atributos(it) a
         WHERE s.pedido_id = p_pedido_id
           AND a.sku IS NOT NULL
    )
    UPDATE public.itens_pedido ip
       SET titulo_anuncio      = coalesce(snap.titulo, ip.titulo_anuncio),
           variacao_externa    = coalesce(snap.variacao, ip.variacao_externa),
           item_externo_id     = coalesce(snap.item_externo_id, ip.item_externo_id),
           variacao_externa_id = coalesce(snap.variacao_externa_id, ip.variacao_externa_id)
      FROM snap
     WHERE ip.pedido_id = p_pedido_id
       AND ip.sku_externo = snap.sku
       AND (ip.titulo_anuncio      IS DISTINCT FROM coalesce(snap.titulo, ip.titulo_anuncio)
         OR ip.variacao_externa    IS DISTINCT FROM coalesce(snap.variacao, ip.variacao_externa)
         OR ip.item_externo_id     IS DISTINCT FROM coalesce(snap.item_externo_id, ip.item_externo_id)
         OR ip.variacao_externa_id IS DISTINCT FROM coalesce(snap.variacao_externa_id, ip.variacao_externa_id));

    GET DIAGNOSTICS v_afetados = ROW_COUNT;
    RETURN v_afetados;
END;
$$;


ALTER FUNCTION "public"."itens_pedido_enriquecer"("p_pedido_id" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."janelas_despacho_vencidas"("p_agora" timestamp with time zone DEFAULT "now"(), "p_desde" interval DEFAULT '24:00:00'::interval) RETURNS TABLE("integration_id" integer, "modalidade_id" integer, "tipo" "text", "janela_em" timestamp with time zone)
    LANGUAGE "sql" STABLE
    AS $$
    WITH regras AS (
        SELECT r.marketplace_integration_id AS integration_id,
               r.modalidade_id,
               r.horario_corte,
               r.horario_coleta,
               COALESCE(r.coleta_dia_offset, 0) AS offset_dias,
               COALESCE(r.dias_semana, ARRAY[1,2,3,4,5,6,7]) AS dias
          FROM public.regras_logisticas_integracao r
          JOIN public.modalidades_logisticas m ON m.id = r.modalidade_id
         WHERE r.ativo AND m.ativo AND m.tipo_prazo = 'FIXO'
           AND m.entra_na_torre
           AND r.horario_corte IS NOT NULL
    ),
    dias AS (
        SELECT generate_series(
                   ((p_agora - p_desde) AT TIME ZONE 'America/Sao_Paulo')::date,
                   (p_agora AT TIME ZONE 'America/Sao_Paulo')::date,
                   interval '1 day'
               )::date AS dia
    ),
    candidatas AS (
        SELECT r.integration_id, r.modalidade_id, g.tipo, g.janela_em
          FROM regras r
          CROSS JOIN dias d
          CROSS JOIN LATERAL (VALUES
                ('CORTE',  ((d.dia + r.horario_corte) AT TIME ZONE 'America/Sao_Paulo')),
                ('COLETA', ((d.dia + r.offset_dias + COALESCE(r.horario_coleta, r.horario_corte))
                             AT TIME ZONE 'America/Sao_Paulo'))
          ) AS g(tipo, janela_em)
         WHERE EXTRACT(isodow FROM d.dia)::integer = ANY (r.dias)
           AND g.janela_em <= p_agora
           AND g.janela_em >  p_agora - p_desde
    )
    SELECT c.integration_id, c.modalidade_id, c.tipo::text, c.janela_em
      FROM candidatas c
     WHERE NOT EXISTS (
           SELECT 1 FROM public.janelas_despacho_execucoes e
            WHERE e.integration_id = c.integration_id
              AND e.modalidade_id  = c.modalidade_id
              AND e.tipo           = c.tipo
              AND e.janela_em      = c.janela_em
     )
     ORDER BY c.janela_em, c.integration_id, c.modalidade_id;
$$;


ALTER FUNCTION "public"."janelas_despacho_vencidas"("p_agora" timestamp with time zone, "p_desde" interval) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."janelas_despacho_vencidas"("p_agora" timestamp with time zone, "p_desde" interval) IS 'Janelas de corte/coleta ja vencidas e nao processadas. E o catch-up: o job nao depende de ter rodado no instante exato.';



CREATE OR REPLACE FUNCTION "public"."janelas_logisticas"("p_modalidade_id" integer, "p_integration_id" integer, "p_dia" "date") RETURNS TABLE("tipo_envio" "text", "coleta_em" timestamp with time zone, "ponto_coleta_id" integer, "ponto_nome" "text")
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT r.tipo_envio::text,
           ((p_dia + COALESCE(r.coleta_dia_offset, 0)
                   -- Ponto de coleta: a saida e a hora em que o ponto fecha,
                   -- salvo excecao cadastrada na propria janela.
                   + COALESCE(r.horario_coleta, pc.horario_fechamento, r.horario_corte))
             AT TIME ZONE 'America/Sao_Paulo'),
           r.ponto_coleta_id,
           pc.nome::text
      FROM public.regras_da_modalidade(p_modalidade_id, p_integration_id) r
      LEFT JOIN public.pontos_coleta pc ON pc.id = r.ponto_coleta_id
     WHERE r.horario_corte IS NOT NULL
       AND EXTRACT(isodow FROM p_dia)::integer = ANY (COALESCE(r.dias_semana, ARRAY[1,2,3,4,5,6,7]))
     ORDER BY 2;
$$;


ALTER FUNCTION "public"."janelas_logisticas"("p_modalidade_id" integer, "p_integration_id" integer, "p_dia" "date") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."janelas_logisticas"("p_modalidade_id" integer, "p_integration_id" integer, "p_dia" "date") IS 'Saidas de despacho de um lote num dia. Um mesmo corte pode ter mais de uma: coleta local as 17h e entrega em ponto de coleta as 19h sao duas chances para o mesmo lote.';



CREATE OR REPLACE FUNCTION "public"."list_pedidos_filtrados"("p_situacao_pedido_id" integer DEFAULT NULL::integer, "p_canal_venda_id" integer DEFAULT NULL::integer, "p_origem_pedido_key" "text" DEFAULT NULL::"text", "p_bling_integration_id" integer DEFAULT NULL::integer, "p_has_demanda" boolean DEFAULT NULL::boolean, "p_is_flex" boolean DEFAULT NULL::boolean, "p_is_personalizado" boolean DEFAULT NULL::boolean, "p_is_fulfillment" boolean DEFAULT NULL::boolean, "p_delivery_start_date" "text" DEFAULT NULL::"text", "p_delivery_end_date" "text" DEFAULT NULL::"text", "p_pedido_date_start" "text" DEFAULT NULL::"text", "p_pedido_date_end" "text" DEFAULT NULL::"text", "p_search_term" "text" DEFAULT NULL::"text", "p_sort" "text" DEFAULT 'numero_pedido'::"text", "p_order" "text" DEFAULT 'desc'::"text", "p_limit" integer DEFAULT 50, "p_offset" integer DEFAULT 0) RETURNS TABLE("id" bigint, "numero_pedido" character varying, "codigo_pedido_externo" character varying, "data_venda" timestamp with time zone, "cliente_nome" character varying, "cliente_documento" character varying, "canal_venda_id" integer, "canal_venda_nome" character varying, "marketplace_integration_id" integer, "marketplace_nome" character varying, "marketplace_slug" character varying, "marketplace_color" character varying, "bling_integration_id" integer, "bling_integration_nome" character varying, "bling_loja_id" character varying, "situacao_pedido_id" integer, "situacao_nome" character varying, "situacao_cor" character varying, "is_flex" boolean, "is_personalizado" boolean, "is_fulfillment" boolean, "modalidade_logistica" character varying, "regra_logistica_integracao_id" bigint, "demanda_id" bigint, "demanda_numero" character varying, "demanda_status" character varying, "total_demandas" bigint, "data_compra_marketplace" timestamp with time zone, "data_pagamento_marketplace" timestamp with time zone, "data_coleta" timestamp with time zone, "data_envio_marketplace" timestamp with time zone, "data_limite_envio" timestamp with time zone, "total_pedido" numeric, "tem_demanda" boolean, "origem" character varying, "created_at" timestamp with time zone, "total_count" bigint)
    LANGUAGE "plpgsql"
    AS $_$
DECLARE
    v_origem_tipo TEXT;
    v_origem_valor TEXT;
BEGIN
    v_origem_tipo := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 1), '');
    v_origem_valor := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 2), '');

    RETURN QUERY
    WITH filtered_pedidos AS (
        SELECT
            p.id,
            p.numero_pedido,
            p.codigo_pedido_externo,
            p.data_venda,
            p.cliente_nome,
            p.cliente_documento,
            p.canal_venda_id,
            p.marketplace_integration_id,
            p.erp_integration_id AS bling_integration_id,
            COALESCE(NULLIF(p.erp_store_id, ''), pb.loja_id::TEXT) AS bling_loja_id,
            p.situacao_pedido_id,
            p.is_flex,
            p.personalizado,
            p.is_fulfillment,
            p.modalidade_logistica,
            p.regra_logistica_integracao_id,
            p.data_compra_marketplace,
            p.data_pagamento_marketplace,
            p.data_coleta,
            p.data_envio_marketplace,
            p.data_limite_envio,
            p.total_pedido,
            p.origem,
            p.created_at,
            p.pedido_bling_id
        FROM public.pedidos p
        LEFT JOIN public.pedidos_bling pb ON pb.id = p.pedido_bling_id
        WHERE
            (p_situacao_pedido_id IS NULL OR p.situacao_pedido_id = p_situacao_pedido_id)
            AND (p_bling_integration_id IS NULL OR p.erp_integration_id = p_bling_integration_id)
            AND (
                p_canal_venda_id IS NULL
                OR p.canal_venda_id = p_canal_venda_id
                OR p.marketplace_integration_id = p_canal_venda_id
            )
            AND (
                p_origem_pedido_key IS NULL
                OR p_origem_pedido_key = ''
                OR (
                    v_origem_tipo = 'source'
                    AND v_origem_valor ~ '^[0-9]+$'
                    AND p.marketplace_integration_id = v_origem_valor::INTEGER
                )
                OR (
                    v_origem_tipo = 'marketplace'
                    AND v_origem_valor ~ '^[0-9]+$'
                    AND p.marketplace_integration_id = v_origem_valor::INTEGER
                )
                OR (
                    v_origem_tipo = 'canal'
                    AND v_origem_valor ~ '^[0-9]+$'
                    AND p.canal_venda_id = v_origem_valor::INTEGER
                )
                OR (
                    v_origem_tipo = 'bling_loja'
                    AND v_origem_valor IS NOT NULL
                    AND (
                        COALESCE(NULLIF(p.erp_store_id, ''), pb.loja_id::TEXT) = v_origem_valor
                        OR EXISTS (
                            SELECT 1
                            FROM public.channel_connections cc
                            WHERE cc.is_active = true
                              AND cc.aggregator_store_id = v_origem_valor
                              AND (
                                  p.erp_integration_id IS NULL
                                  OR cc.bling_integration_id IS NULL
                                  OR cc.bling_integration_id = p.erp_integration_id
                              )
                              AND (
                                  cc.marketplace_integration_id = p.marketplace_integration_id
                                  OR cc.channel_id = p.canal_venda_id
                              )
                        )
                    )
                )
            )
            AND (
                p_has_demanda IS NULL OR
                (p_has_demanda = TRUE AND EXISTS (
                    SELECT 1 FROM public.demandas_pedidos dp WHERE dp.pedido_id = p.id
                )) OR
                (p_has_demanda = FALSE AND NOT EXISTS (
                    SELECT 1 FROM public.demandas_pedidos dp WHERE dp.pedido_id = p.id
                ))
            )
            AND (p_is_flex IS NULL OR p.is_flex = p_is_flex)
            AND (p_is_personalizado IS NULL OR p.personalizado = p_is_personalizado)
            AND (p_is_fulfillment IS NULL OR p.is_fulfillment = p_is_fulfillment)
            AND (p_delivery_start_date IS NULL OR p.data_limite_envio >= p_delivery_start_date::TIMESTAMPTZ)
            AND (p_delivery_end_date IS NULL OR p.data_limite_envio <= p_delivery_end_date::TIMESTAMPTZ)
            AND (p_pedido_date_start IS NULL OR p.data_venda::DATE >= p_pedido_date_start::DATE)
            AND (p_pedido_date_end IS NULL OR p.data_venda::DATE <= p_pedido_date_end::DATE)
            AND (p_search_term IS NULL OR p_search_term = '' OR
                p.numero_pedido ILIKE '%' || p_search_term || '%' OR
                p.cliente_nome ILIKE '%' || p_search_term || '%' OR
                p.codigo_pedido_externo ILIKE '%' || p_search_term || '%' OR
                p.cliente_documento ILIKE '%' || p_search_term || '%'
            )
    )
    SELECT
        f.id::BIGINT,
        f.numero_pedido::VARCHAR,
        f.codigo_pedido_externo::VARCHAR,
        f.data_venda::TIMESTAMPTZ,
        f.cliente_nome::VARCHAR,
        f.cliente_documento::VARCHAR,
        f.canal_venda_id,
        cv.nome::VARCHAR AS canal_venda_nome,
        f.marketplace_integration_id,
        ii.instance_name::VARCHAR AS marketplace_nome,
        im.slug::VARCHAR AS marketplace_slug,
        (CASE
            WHEN im.slug = 'shopee' THEN '#EE4D2D'
            WHEN im.slug = 'mercadolivre' THEN '#FFF159'
            WHEN im.slug = 'amazon' THEN '#FF9900'
            WHEN im.slug = 'shein' THEN '#FF6B6B'
            ELSE '#007bff'
        END)::VARCHAR AS marketplace_color,
        f.bling_integration_id,
        bi.instance_name::VARCHAR AS bling_integration_nome,
        f.bling_loja_id::VARCHAR AS bling_loja_id,
        f.situacao_pedido_id,
        sp.nome::VARCHAR AS situacao_nome,
        sp.cor_status::VARCHAR AS situacao_cor,
        f.is_flex,
        f.personalizado AS is_personalizado,
        f.is_fulfillment,
        f.modalidade_logistica::VARCHAR,
        f.regra_logistica_integracao_id::BIGINT,
        v.demanda_id::BIGINT,
        v.demanda_numero::VARCHAR,
        v.demanda_status::VARCHAR,
        v.total_demandas::BIGINT,
        f.data_compra_marketplace,
        f.data_pagamento_marketplace,
        f.data_coleta,
        f.data_envio_marketplace,
        f.data_limite_envio,
        f.total_pedido,
        (v.demanda_id IS NOT NULL) AS tem_demanda,
        f.origem::VARCHAR,
        f.created_at::TIMESTAMPTZ,
        COUNT(*) OVER()::BIGINT AS total_count
    FROM filtered_pedidos f
    LEFT JOIN public.canais_venda cv ON f.canal_venda_id = cv.id
    LEFT JOIN public.installed_integrations ii ON f.marketplace_integration_id = ii.id
    LEFT JOIN public.installed_integrations bi ON f.bling_integration_id = bi.id
    LEFT JOIN public.integration_modules im ON ii.module_id = im.id
    LEFT JOIN public.situacoes_pedido sp ON f.situacao_pedido_id = sp.id
    LEFT JOIN public.v_pedido_demanda_rastreamento v ON v.pedido_id = f.id
    ORDER BY
        CASE WHEN p_sort = 'numero_pedido' AND p_order = 'desc' THEN NULLIF(regexp_replace(f.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT END DESC NULLS LAST,
        CASE WHEN p_sort = 'numero_pedido' AND p_order = 'asc' THEN NULLIF(regexp_replace(f.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT END ASC NULLS LAST,
        CASE WHEN p_sort = 'data_venda' AND p_order = 'desc' THEN f.data_venda END DESC NULLS LAST,
        CASE WHEN p_sort = 'data_venda' AND p_order = 'asc' THEN f.data_venda END ASC NULLS LAST,
        CASE WHEN p_sort = 'created_at' AND p_order = 'desc' THEN f.created_at END DESC NULLS LAST,
        CASE WHEN p_sort = 'created_at' AND p_order = 'asc' THEN f.created_at END ASC NULLS LAST,
        f.data_limite_envio ASC NULLS LAST,
        f.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$_$;


ALTER FUNCTION "public"."list_pedidos_filtrados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_sort" "text", "p_order" "text", "p_limit" integer, "p_offset" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."list_pedidos_filtrados_v2"("p_limit" integer, "p_offset" integer, "p_sort" "text", "p_order" "text", "p_origem_pedido_key" "text", "p_situacao_pedido_id" integer DEFAULT NULL::integer, "p_bling_integration_id" integer DEFAULT NULL::integer, "p_canal_venda_id" integer DEFAULT NULL::integer, "p_has_demanda" boolean DEFAULT NULL::boolean, "p_is_flex" boolean DEFAULT NULL::boolean, "p_is_personalizado" boolean DEFAULT NULL::boolean, "p_delivery_start_date" timestamp without time zone DEFAULT NULL::timestamp without time zone, "p_delivery_end_date" timestamp without time zone DEFAULT NULL::timestamp without time zone, "p_pedido_date_start" "date" DEFAULT NULL::"date", "p_pedido_date_end" "date" DEFAULT NULL::"date", "p_search_term" "text" DEFAULT NULL::"text") RETURNS TABLE("id" bigint, "numero_pedido" character varying, "codigo_pedido_externo" character varying, "data_venda" timestamp with time zone, "cliente_nome" character varying, "cliente_documento" character varying, "canal_venda_id" integer, "canal_venda_nome" character varying, "marketplace_integration_id" integer, "marketplace_nome" character varying, "marketplace_slug" character varying, "marketplace_color" character varying, "bling_integration_id" integer, "bling_integration_nome" character varying, "situacao_pedido_id" integer, "situacao_nome" character varying, "situacao_cor" character varying, "is_flex" boolean, "is_personalizado" boolean, "demanda_id" bigint, "demanda_numero" character varying, "demanda_status" character varying, "total_demandas" bigint, "data_limite_envio" timestamp with time zone, "total_pedido" numeric, "tem_demanda" boolean, "origem" character varying, "created_at" timestamp with time zone)
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_origem_tipo TEXT;
    v_origem_valor TEXT;
BEGIN
    v_origem_tipo := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 1), '');
    v_origem_valor := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 2), '');

    RETURN QUERY
    SELECT
        p.id::BIGINT AS id,
        p.numero_pedido::VARCHAR,
        p.codigo_pedido_externo::VARCHAR,
        p.data_venda::TIMESTAMPTZ AS data_venda,
        p.cliente_nome::VARCHAR,
        p.cliente_documento::VARCHAR,
        p.canal_venda_id,
        cv.nome::VARCHAR AS canal_venda_nome,
        p.marketplace_integration_id,
        ii.instance_name::VARCHAR AS marketplace_nome,
        im.slug::VARCHAR AS marketplace_slug,
        (CASE
            WHEN im.slug = 'shopee' THEN '#EE4D2D'
            WHEN im.slug = 'mercadolivre' THEN '#FFF159'
            WHEN im.slug = 'amazon' THEN '#FF9900'
            WHEN im.slug = 'shein' THEN '#FF6B6B'
            ELSE '#007bff'
        END)::VARCHAR AS marketplace_color,
        p.erp_integration_id AS bling_integration_id,
        bi.instance_name::VARCHAR AS bling_integration_nome,
        p.situacao_pedido_id,
        sp.nome::VARCHAR AS situacao_nome,
        sp.cor_status::VARCHAR AS situacao_cor,
        p.is_flex,
        p.personalizado AS is_personalizado,
        v.demanda_id::BIGINT,
        v.demanda_numero::VARCHAR,
        v.demanda_status::VARCHAR,
        v.total_demandas::BIGINT,
        p.data_limite_envio,
        p.total_pedido,
        EXISTS (
            SELECT 1 FROM public.demandas_pedidos dp
            WHERE dp.pedido_id = p.id
        ) AS tem_demanda,
        p.origem::VARCHAR,
        p.created_at::TIMESTAMPTZ AS created_at
    FROM public.pedidos p
    LEFT JOIN public.canais_venda cv ON p.canal_venda_id = cv.id
    LEFT JOIN public.installed_integrations ii ON p.marketplace_integration_id = ii.id
    LEFT JOIN public.installed_integrations bi ON p.erp_integration_id = bi.id
    LEFT JOIN public.integration_modules im ON ii.module_id = im.id
    LEFT JOIN public.situacoes_pedido sp ON p.situacao_pedido_id = sp.id
    LEFT JOIN public.v_pedido_demanda_rastreamento v ON v.pedido_id = p.id
    LEFT JOIN public.pedidos_bling pb ON pb.id = p.pedido_bling_id
    WHERE
        (p_situacao_pedido_id IS NULL OR p.situacao_pedido_id = p_situacao_pedido_id)
        AND (p_bling_integration_id IS NULL OR p.erp_integration_id = p_bling_integration_id)
        AND (
            p_origem_pedido_key IS NULL
            OR p_origem_pedido_key = ''
            OR (
                v_origem_tipo = 'loja'
                AND COALESCE(NULLIF(p.erp_store_id, ''), pb.loja_id::TEXT) = v_origem_valor
            )
        )
        AND (p_has_demanda IS NULL OR
            (p_has_demanda = TRUE AND EXISTS (
                SELECT 1 FROM public.demandas_pedidos dp WHERE dp.pedido_id = p.id
            )) OR
            (p_has_demanda = FALSE AND NOT EXISTS (
                SELECT 1 FROM public.demandas_pedidos dp WHERE dp.pedido_id = p.id
            ))
        )
        AND (p_is_flex IS NULL OR p.is_flex = p_is_flex)
        AND (p_is_personalizado IS NULL OR p.personalizado = p_is_personalizado)
        AND (p_delivery_start_date IS NULL OR p.data_limite_envio >= p_delivery_start_date::TIMESTAMPTZ)
        AND (p_delivery_end_date IS NULL OR p.data_limite_envio <= p_delivery_end_date::TIMESTAMPTZ)
        AND (p_pedido_date_start IS NULL OR p.data_venda::DATE >= p_pedido_date_start::DATE)
        AND (p_pedido_date_end IS NULL OR p.data_venda::DATE <= p_pedido_date_end::DATE)
        AND (p_search_term IS NULL OR p_search_term = '' OR
            p.numero_pedido ILIKE '%' || p_search_term || '%' OR
            p.cliente_nome ILIKE '%' || p_search_term || '%' OR
            p.codigo_pedido_externo ILIKE '%' || p_search_term || '%' OR
            p.cliente_documento ILIKE '%' || p_search_term || '%'
        )
    ORDER BY
        CASE
            WHEN p_order = 'desc' THEN
                NULLIF(regexp_replace(p.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT
            ELSE NULL
        END DESC NULLS LAST,
        CASE
            WHEN p_order = 'asc' THEN
                NULLIF(regexp_replace(p.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT
            ELSE NULL
        END ASC NULLS LAST,
        p.data_limite_envio ASC NULLS LAST,
        p.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;


ALTER FUNCTION "public"."list_pedidos_filtrados_v2"("p_limit" integer, "p_offset" integer, "p_sort" "text", "p_order" "text", "p_origem_pedido_key" "text", "p_situacao_pedido_id" integer, "p_bling_integration_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_delivery_start_date" timestamp without time zone, "p_delivery_end_date" timestamp without time zone, "p_pedido_date_start" "date", "p_pedido_date_end" "date", "p_search_term" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."list_pedidos_por_compra"("p_situacao_pedido_id" integer DEFAULT NULL::integer, "p_canal_venda_id" integer DEFAULT NULL::integer, "p_origem_pedido_key" "text" DEFAULT NULL::"text", "p_bling_integration_id" integer DEFAULT NULL::integer, "p_has_demanda" boolean DEFAULT NULL::boolean, "p_is_flex" boolean DEFAULT NULL::boolean, "p_is_personalizado" boolean DEFAULT NULL::boolean, "p_is_fulfillment" boolean DEFAULT NULL::boolean, "p_delivery_start_date" "text" DEFAULT NULL::"text", "p_delivery_end_date" "text" DEFAULT NULL::"text", "p_pedido_date_start" "text" DEFAULT NULL::"text", "p_pedido_date_end" "text" DEFAULT NULL::"text", "p_search_term" "text" DEFAULT NULL::"text", "p_limit" integer DEFAULT 50, "p_offset" integer DEFAULT 0) RETURNS TABLE("order_data" "jsonb")
    LANGUAGE "sql" STABLE
    AS $$
  SELECT to_jsonb(row_data)
  FROM public.list_pedidos_filtrados(
    p_situacao_pedido_id, p_canal_venda_id, p_origem_pedido_key,
    p_bling_integration_id, p_has_demanda, p_is_flex, p_is_personalizado,
    p_is_fulfillment, p_delivery_start_date, p_delivery_end_date,
    p_pedido_date_start, p_pedido_date_end, p_search_term,
    'created_at', 'desc', 2147483647, 0
  ) AS row_data
  ORDER BY COALESCE(
    row_data.data_compra_marketplace,
    row_data.data_venda,
    row_data.created_at
  ) DESC NULLS LAST, row_data.id DESC
  LIMIT p_limit OFFSET p_offset;
$$;


ALTER FUNCTION "public"."list_pedidos_por_compra"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."listar_produtos_prontidao"("p_tag_id" integer DEFAULT NULL::integer, "p_estagio" "public"."estagio_produto" DEFAULT NULL::"public"."estagio_produto") RETURNS TABLE("produto_id" integer, "estagio" "public"."estagio_produto", "sku" "text", "nome" "text", "categoria_id" integer, "tem_ficha" boolean, "tem_miolo" boolean, "tem_capa" boolean, "tem_contra" boolean, "tem_acabamento" boolean, "ficha_completa" boolean, "exige_arte" boolean, "arte_confirmada" boolean, "eixos_completos" boolean, "tem_apelido_externo" boolean, "tem_custo" boolean, "tem_anuncio" boolean, "proximo_estagio" "public"."estagio_produto", "pendencias" "text"[], "tags" "text"[])
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public'
    AS $$ SELECT pp.* FROM public.produtos p CROSS JOIN LATERAL public.produto_prontidao(p.id) pp WHERE (p_tag_id IS NULL OR EXISTS (SELECT 1 FROM public.produto_tags pt WHERE pt.produto_id=pp.produto_id AND pt.tag_id=p_tag_id)) AND (p_estagio IS NULL OR pp.estagio=p_estagio) ORDER BY pp.produto_id; $$;


ALTER FUNCTION "public"."listar_produtos_prontidao"("p_tag_id" integer, "p_estagio" "public"."estagio_produto") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."manutencao_desfazer_lote"("p_lote" "uuid") RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_total integer;
BEGIN
    UPDATE public.pedidos p
       SET situacao_pedido_id = l.situacao_anterior_id,
           despachado_em      = l.despachado_em_anterior,
           updated_at         = now()
      FROM public.manutencao_status_log l
     WHERE l.lote = p_lote
       AND p.id = l.pedido_id;

    GET DIAGNOSTICS v_total = ROW_COUNT;

    DELETE FROM public.manutencao_status_log WHERE lote = p_lote;

    RETURN v_total;
END;
$$;


ALTER FUNCTION "public"."manutencao_desfazer_lote"("p_lote" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."manutencao_desfazer_lote"("p_lote" "uuid") IS 'Restaura situacao_pedido_id e despachado_em ao estado anterior ao lote e limpa o log. E o que torna o corte historico uma decisao reversivel.';



CREATE OR REPLACE FUNCTION "public"."manutencao_marcar_entregues_ate"("p_data" "date", "p_dry_run" boolean DEFAULT true, "p_executado_por" "text" DEFAULT 'System'::"text") RETURNS TABLE("out_lote" "uuid", "out_situacao_anterior" "text", "out_qtd" integer)
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    c_pendentes   constant integer[] := ARRAY[1, 2, 3, 4, 5];
    c_entregue    constant integer   := 6;
    v_lote        uuid := gen_random_uuid();
BEGIN
    IF p_data IS NULL THEN
        RAISE EXCEPTION 'Data de corte e obrigatoria' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    CREATE TEMP TABLE tmp_alvo ON COMMIT DROP AS
    SELECT p.id AS pedido_id,
           p.situacao_pedido_id,
           p.despachado_em
      FROM public.pedidos p
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id = ANY (c_pendentes)
       AND p.data_venda < (p_data + 1)::timestamp;

    IF NOT p_dry_run THEN
        INSERT INTO public.manutencao_status_log (
            operacao, lote, pedido_id, situacao_anterior_id,
            situacao_nova_id, despachado_em_anterior, executado_por
        )
        SELECT 'marcar_entregues_ate', v_lote, a.pedido_id, a.situacao_pedido_id,
               c_entregue, a.despachado_em, p_executado_por
          FROM tmp_alvo a;

        UPDATE public.pedidos p
           SET situacao_pedido_id = c_entregue,
               despachado_em      = now(),
               updated_at         = now()
          FROM tmp_alvo a
         WHERE p.id = a.pedido_id;
    END IF;

    RETURN QUERY
    SELECT v_lote,
           COALESCE(sp.nome, 'Sem situacao')::text,
           count(*)::integer
      FROM tmp_alvo a
      LEFT JOIN public.situacoes_pedido sp ON sp.id = a.situacao_pedido_id
     GROUP BY sp.nome
     ORDER BY count(*) DESC;
END;
$$;


ALTER FUNCTION "public"."manutencao_marcar_entregues_ate"("p_data" "date", "p_dry_run" boolean, "p_executado_por" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."manutencao_marcar_entregues_ate"("p_data" "date", "p_dry_run" boolean, "p_executado_por" "text") IS 'Corte historico: marca como Entregue e carimba despachado_em nos pedidos ainda pendentes (Em Aberto/Em Andamento/Produzido/Pronto para Envio/Enviado) com data_venda ate p_data — situacao presa por falta de atualizacao. Nao toca Cancelado/Entregue/Devolvido (situacoes finais) nem situacao nula. p_dry_run=true devolve a previa sem alterar. Desfazer: manutencao_desfazer_lote(lote).';



CREATE OR REPLACE FUNCTION "public"."marcar_alocacao_processada"("p_correlation_id" character varying) RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    UPDATE "public"."demanda_alocacoes_estoque"
    SET status = 'PROCESSADA',
        processed_at = NOW()
    WHERE correlation_id = p_correlation_id
    AND status = 'PENDENTE';
END;
$$;


ALTER FUNCTION "public"."marcar_alocacao_processada"("p_correlation_id" character varying) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."miolo_do_sku"("p_sku" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE PARALLEL SAFE
    AS $$
SELECT upper(btrim(
    CASE
        WHEN position('CMB_VACMNA' in left(btrim(coalesce(p_sku, '-')), 10)) > 0 THEN 'CMBMNA'
        WHEN position('CMB_VACMNO' in left(btrim(coalesce(p_sku, '-')), 10)) > 0 THEN 'CMBMNO'
        WHEN left(btrim(coalesce(p_sku, '-')), 10) = 'PLANGEST01' THEN 'GESTAN'
        WHEN left(btrim(coalesce(p_sku, '-')),  8) = 'CONFINNV'   THEN 'CONFIN25'
        WHEN left(btrim(coalesce(p_sku, '-')),  8) = 'CONFIN25'   THEN 'CONFIN25'
        WHEN position('PB25' in left(btrim(coalesce(p_sku, '-')), 6)) > 0 THEN 'PB25'
        WHEN position('PB26' in left(btrim(coalesce(p_sku, '-')), 6)) > 0 THEN 'PB26'
        WHEN left(btrim(coalesce(p_sku, '-')), 6) = 'CADMNA' THEN 'VACMNA'
        WHEN left(btrim(coalesce(p_sku, '-')), 6) = 'DEVNP_' THEN 'DEVNP'
        WHEN left(btrim(coalesce(p_sku, '-')), 6) = 'CADAGE' THEN 'PTD200'
        WHEN left(btrim(coalesce(p_sku, '-')), 6) = 'CADMOS' THEN 'VACMNO'
        WHEN left(btrim(coalesce(p_sku, '-')), 6) = 'CADREL' THEN 'RECTAS'
        WHEN left(btrim(coalesce(p_sku, '-')), 6) = 'PLANPR' THEN 'PNJPRO'
        WHEN left(btrim(coalesce(p_sku, '-')), 6) = 'CADFL'  THEN 'PTD200'
        ELSE left(btrim(coalesce(p_sku, '-')), 6)
    END))
$$;


ALTER FUNCTION "public"."miolo_do_sku"("p_sku" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."miolo_do_sku"("p_sku" "text") IS 'Miolo derivado do codigo do SKU, equivalente a apply_miolo_fixes(resolve_miolo(sku,10)) do legado (checksum identico nos 435 SKUs do historico). Expressao unica e SEM SET search_path de proposito: as duas coisas sao o que permitem ao planner inlina-la. Nao toca tabela e so usa funcoes de pg_catalog, entao o search_path mutavel apontado pelo linter nao e explorave aqui.';



CREATE OR REPLACE FUNCTION "public"."normalize_text_for_flex"("input_text" "text") RETURNS "text"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    result TEXT;
BEGIN
    IF input_text IS NULL THEN
        RETURN NULL;
    END IF;
    
    -- Converter para maiúsculas
    result := UPPER(input_text);
    
    -- Remover acentos comuns em português (cada REPLACE remove um tipo de acento)
    result := REPLACE(result, 'Á', 'A');
    result := REPLACE(result, 'À', 'A');
    result := REPLACE(result, 'Ã', 'A');
    result := REPLACE(result, 'Â', 'A');
    result := REPLACE(result, 'É', 'E');
    result := REPLACE(result, 'È', 'E');
    result := REPLACE(result, 'Ê', 'E');
    result := REPLACE(result, 'Í', 'I');
    result := REPLACE(result, 'Ì', 'I');
    result := REPLACE(result, 'Î', 'I');
    result := REPLACE(result, 'Ó', 'O');
    result := REPLACE(result, 'Ò', 'O');
    result := REPLACE(result, 'Õ', 'O');
    result := REPLACE(result, 'Ô', 'O');
    result := REPLACE(result, 'Ú', 'U');
    result := REPLACE(result, 'Ù', 'U');
    result := REPLACE(result, 'Û', 'U');
    result := REPLACE(result, 'Ç', 'C');
    result := REPLACE(result, 'Ñ', 'N');
    
    -- Remover espaços e hífens
    result := REPLACE(result, ' ', '_');
    result := REPLACE(result, '-', '_');
    
    RETURN result;
END;
$$;


ALTER FUNCTION "public"."normalize_text_for_flex"("input_text" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."pedidos_pacotes"("p_pedido_ids" bigint[]) RETURNS TABLE("pedido_id" bigint, "pack_id" "text", "irmaos" integer, "irmaos_ids" bigint[], "irmaos_numeros" "text"[])
    LANGUAGE "sql" STABLE
    AS $$
    SELECT
        p.id,
        p.pack_id,
        (pk.total - 1)::integer,
        pk.ids,
        pk.numeros
      FROM public.pedidos p
      JOIN LATERAL (
            SELECT count(*) AS total,
                   array_agg(irmao.id ORDER BY irmao.id) FILTER (WHERE irmao.id <> p.id) AS ids,
                   array_agg(irmao.marketplace_order_id ORDER BY irmao.id)
                     FILTER (WHERE irmao.id <> p.id) AS numeros
              FROM public.pedidos irmao
             WHERE irmao.pack_id = p.pack_id
      ) pk ON true
     WHERE p.id = ANY (p_pedido_ids)
       AND p.pack_id IS NOT NULL
       -- Pacote de um pedido so nao e pacote: nao ha nada para agrupar, e um
       -- marcador nesse caso seria ruido em 138 dos 146 pedidos com pack_id.
       AND pk.total > 1;
$$;


ALTER FUNCTION "public"."pedidos_pacotes"("p_pedido_ids" bigint[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."pedidos_pacotes"("p_pedido_ids" bigint[]) IS 'Irmaos de pacote dos pedidos informados. Devolve apenas pacotes com mais de um pedido — os que compartilham numero_pedido e pareceriam duplicatas na tela.';



CREATE OR REPLACE FUNCTION "public"."process_marketplace_order_effect"("p_effect_id" bigint) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  v_effect public.marketplace_order_effects%ROWTYPE;
  v_link RECORD;
  v_alert_count INTEGER := 0;
  v_removed_count INTEGER := 0;
  v_is_returned BOOLEAN;
  v_qtd_pedido INTEGER;
  v_rotulo TEXT;
BEGIN
  SELECT * INTO v_effect
  FROM public.marketplace_order_effects
  WHERE id = p_effect_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'marketplace_order_effect % not found', p_effect_id;
  END IF;
  IF v_effect.status = 'processed' THEN
    RETURN jsonb_build_object('effect_id', p_effect_id, 'status', 'processed', 'alerts', 0);
  END IF;

  v_is_returned := COALESCE(v_effect.payload->>'lifecycle_stage', '') = 'returned';
  v_rotulo := CASE WHEN v_is_returned THEN 'devolvido' ELSE 'cancelado' END;

  FOR v_link IN
    SELECT dp.demanda_id
    FROM public.demandas_pedidos dp
    JOIN public.demandas_producao d ON d.id = dp.demanda_id
    WHERE dp.pedido_id = v_effect.pedido_id
      AND d.status IN ('AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'COLETADO')
  LOOP
    INSERT INTO public.alertas_demanda (
      demanda_id, tipo_alerta, severidade, titulo, mensagem,
      dados_impacto, requer_acao, created_at
    ) VALUES (
      v_link.demanda_id,
      CASE WHEN v_is_returned THEN 'PEDIDO_DEVOLVIDO' ELSE 'PEDIDO_CANCELADO' END,
      'media',
      CASE WHEN v_is_returned THEN 'Pedido devolvido na demanda' ELSE 'Pedido cancelado na demanda' END,
      format(
        'Pedido %s foi %s pelo marketplace; revise a demanda.',
        COALESCE(v_effect.payload->>'external_order_id', v_effect.pedido_id::text),
        v_rotulo
      ),
      jsonb_build_object(
        'pedido_id', v_effect.pedido_id,
        'transition_id', v_effect.transition_id,
        'effect_id', v_effect.id,
        'lifecycle_stage', v_effect.payload->>'lifecycle_stage'
      ),
      true,
      now()
    );
    UPDATE public.demandas_producao
       SET requer_revisao = true, updated_at = now()
     WHERE id = v_link.demanda_id;
    v_alert_count := v_alert_count + 1;
  END LOOP;

  FOR v_link IN
    SELECT dp.id AS vinculo_id, dp.demanda_id
    FROM public.demandas_pedidos dp
    JOIN public.demandas_producao d ON d.id = dp.demanda_id
    WHERE dp.pedido_id = v_effect.pedido_id
      AND d.status = 'RASCUNHO'
  LOOP
    SELECT COALESCE(SUM(ip.quantidade), 0)::INTEGER INTO v_qtd_pedido
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = v_effect.pedido_id;

    DELETE FROM public.demandas_pedidos WHERE id = v_link.vinculo_id;

    UPDATE public.demandas_producao
       SET quantidade = GREATEST(COALESCE(quantidade, 0) - COALESCE(v_qtd_pedido, 0), 0),
           updated_at = now()
     WHERE id = v_link.demanda_id;

    INSERT INTO public.alertas_demanda (
      demanda_id, tipo_alerta, severidade, titulo, mensagem,
      dados_impacto, requer_acao, created_at
    ) VALUES (
      v_link.demanda_id,
      'PEDIDO_REMOVIDO_RASCUNHO',
      'baixa',
      format('Pedido %s removido do rascunho', v_rotulo),
      format(
        'Pedido %s foi %s pelo marketplace e saiu automaticamente do rascunho (%s un.).',
        COALESCE(v_effect.payload->>'external_order_id', v_effect.pedido_id::text),
        v_rotulo,
        COALESCE(v_qtd_pedido, 0)
      ),
      jsonb_build_object(
        'pedido_id', v_effect.pedido_id,
        'transition_id', v_effect.transition_id,
        'effect_id', v_effect.id,
        'quantidade_removida', COALESCE(v_qtd_pedido, 0),
        'lifecycle_stage', v_effect.payload->>'lifecycle_stage'
      ),
      false,
      now()
    );
    v_removed_count := v_removed_count + 1;
  END LOOP;

  INSERT INTO public.eventos_pedido (
    pedido_id, tipo_evento, descricao, status_para, metadata, created_at
  ) VALUES (
    v_effect.pedido_id,
    CASE WHEN v_is_returned THEN 'ORDER_RETURNED_MARKETPLACE' ELSE 'ORDER_CANCELLED_MARKETPLACE' END,
    CASE WHEN v_is_returned THEN 'Pedido devolvido pelo marketplace' ELSE 'Pedido cancelado pelo marketplace' END,
    CASE WHEN v_is_returned THEN '8' ELSE '7' END,
    jsonb_build_object(
      'transition_id', v_effect.transition_id,
      'effect_id', v_effect.id,
      'alertas_demanda', v_alert_count,
      'removido_de_rascunhos', v_removed_count
    ),
    now()
  );

  UPDATE public.marketplace_order_effects
     SET status = 'processed', processed_at = now(), updated_at = now(),
         attempt_count = attempt_count + 1, last_error = NULL
   WHERE id = p_effect_id;

  RETURN jsonb_build_object(
    'effect_id', p_effect_id,
    'status', 'processed',
    'alerts', v_alert_count,
    'removed_from_drafts', v_removed_count
  );
END;
$$;


ALTER FUNCTION "public"."process_marketplace_order_effect"("p_effect_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."produto_prontidao"("p_produto_id" integer) RETURNS TABLE("produto_id" integer, "estagio" "public"."estagio_produto", "sku" "text", "nome" "text", "categoria_id" integer, "tem_ficha" boolean, "tem_miolo" boolean, "tem_capa" boolean, "tem_contra" boolean, "tem_acabamento" boolean, "ficha_completa" boolean, "exige_arte" boolean, "arte_confirmada" boolean, "eixos_completos" boolean, "tem_apelido_externo" boolean, "tem_custo" boolean, "tem_anuncio" boolean, "proximo_estagio" "public"."estagio_produto", "pendencias" "text"[], "tags" "text"[])
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public'
    AS $$
WITH p AS (
  SELECT pr.*, c.permite_arte FROM public.produtos pr
   LEFT JOIN public.categorias c ON c.id = pr.categoria_id WHERE pr.id = p_produto_id
),
bom AS (
  SELECT public.grupo_bom_do_componente(b.componente_id, b.grupo) AS grupo
    FROM public.bom_efetiva_produto(p_produto_id) b
),
gates AS (
  SELECT p.*,
    EXISTS (SELECT 1 FROM bom) AS tem_ficha,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'MIOLO') AS tem_miolo,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'CAPA') AS tem_capa,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'CONTRA') AS tem_contra,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'ACABAMENTO') AS tem_acabamento,
    (NOT EXISTS (SELECT 1 FROM public.categoria_bom_regras r WHERE r.categoria_pai_id = p.categoria_id)
     OR NOT EXISTS (SELECT 1 FROM public.categoria_bom_regras r
                     WHERE r.categoria_pai_id = p.categoria_id
                       AND NOT EXISTS (SELECT 1 FROM bom WHERE bom.grupo = upper(r.nome_grupo)))
    ) AS ficha_completa,
    (coalesce(p.permite_arte, false)
     OR EXISTS (SELECT 1 FROM public.bom_efetiva_produto(p.id) b
                 JOIN public.produtos c ON c.id = b.componente_id
                 JOIN public.categorias cc ON cc.id = c.categoria_id
                WHERE cc.permite_arte)) AS exige_arte,
    (p.arte_confirmada_em IS NOT NULL) AS arte_confirmada,
    (p.parent_id IS NULL OR NOT EXISTS (
       SELECT 1 FROM public.produto_pai_eixos pe
        WHERE pe.produto_pai_id = p.parent_id
          AND NOT EXISTS (SELECT 1 FROM public.produto_variacao_valores vv
                           WHERE vv.produto_id = p.id AND vv.eixo_id = pe.eixo_id))) AS eixos_completos,
    EXISTS (SELECT 1 FROM public.produtos_externos e WHERE e.produto_id = p.id) AS tem_apelido_externo,
    (coalesce(p.preco_custo, 0) > 0) AS tem_custo,
    EXISTS (SELECT 1 FROM public.produto_anuncios a WHERE a.produto_id = p.id AND a.status = 'ativo') AS tem_anuncio
  FROM p
),
resultado AS (
  SELECT g.*, array_remove(ARRAY[
    CASE WHEN NOT g.tem_ficha THEN 'sem ficha' END,
    CASE WHEN NOT g.ficha_completa THEN 'ficha incompleta' END,
    CASE WHEN g.exige_arte AND NOT g.arte_confirmada THEN 'arte não confirmada pelo agente' END,
    CASE WHEN NOT g.eixos_completos THEN 'eixos incompletos' END,
    CASE WHEN NOT g.tem_apelido_externo THEN 'sem apelido externo' END,
    CASE WHEN NOT g.tem_custo THEN 'sem custo' END], NULL) AS pendencias
  FROM gates g
)
SELECT r.id, r.estagio, r.sku::text, r.nome::text, r.categoria_id, r.tem_ficha, r.tem_miolo,
       r.tem_capa, r.tem_contra, r.tem_acabamento, r.ficha_completa, r.exige_arte,
       r.arte_confirmada, r.eixos_completos, r.tem_apelido_externo, r.tem_custo, r.tem_anuncio,
       CASE WHEN cardinality(r.pendencias) = 0 THEN 'PUBLICADO'::public.estagio_produto
            WHEN r.exige_arte AND NOT r.arte_confirmada THEN 'ARTE_PENDENTE'::public.estagio_produto
            WHEN NOT r.ficha_completa OR NOT r.eixos_completos THEN 'FICHA_OK'::public.estagio_produto
            WHEN NOT r.tem_apelido_externo OR NOT r.tem_anuncio THEN 'CANAL_OK'::public.estagio_produto
            ELSE 'RASCUNHO'::public.estagio_produto END,
       r.pendencias,
       coalesce((SELECT array_agg(t.nome ORDER BY t.nome) FROM public.produto_tags pt
                  JOIN public.tags t ON t.id = pt.tag_id WHERE pt.produto_id = r.id), '{}'::text[])
  FROM resultado r;
$$;


ALTER FUNCTION "public"."produto_prontidao"("p_produto_id" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."proxima_janela_logistica"("p_modalidade_id" integer, "p_integration_id" integer, "p_agora" timestamp with time zone DEFAULT "now"()) RETURNS TABLE("corte_em" timestamp with time zone, "coleta_em" timestamp with time zone)
    LANGUAGE "plpgsql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    c_tz     constant text := 'America/Sao_Paulo';
    v_tipo   text;
    v_corte  time;
    v_coleta time;
    v_offset smallint;
    v_dias   integer[];
    v_dia    date;
    v_corte_dt timestamptz;
    d        integer;
BEGIN
    IF p_modalidade_id IS NULL THEN
        RETURN;
    END IF;

    SELECT ml.tipo_prazo,
           COALESCE(r.horario_corte,  ml.corte_horario),
           COALESCE(r.horario_coleta, pc.horario_fechamento, ml.coleta_horario),
           COALESCE(r.coleta_dia_offset, ml.coleta_dia_offset, 0),
           COALESCE(r.dias_semana, ARRAY[1,2,3,4,5,6,7])
      INTO v_tipo, v_corte, v_coleta, v_offset, v_dias
      FROM public.modalidades_logisticas ml
      LEFT JOIN LATERAL public.regras_da_modalidade(ml.id, p_integration_id) r ON true
      LEFT JOIN public.pontos_coleta pc ON pc.id = r.ponto_coleta_id
     WHERE ml.id = p_modalidade_id
     ORDER BY r.prioridade_uso DESC NULLS LAST, r.id
     LIMIT 1;

    -- Prazo relativo nao tem janela recorrente: cada pedido tem o proprio
    -- relogio, ancorado na venda. Quem precisa disso le
    -- pedidos.compromisso_logistico_em.
    IF v_tipo IS DISTINCT FROM 'FIXO' OR v_corte IS NULL THEN
        RETURN;
    END IF;

    FOR d IN 0..14 LOOP
        v_dia := (p_agora AT TIME ZONE c_tz)::date + d;

        IF NOT (EXTRACT(isodow FROM v_dia)::integer = ANY (v_dias)) THEN
            CONTINUE;
        END IF;

        v_corte_dt := ((v_dia + v_corte) AT TIME ZONE c_tz);

        -- Corte que ja passou nao aceita mais pedido: o lote dele foi fechado.
        IF v_corte_dt <= p_agora THEN
            CONTINUE;
        END IF;

        corte_em  := v_corte_dt;
        coleta_em := ((v_dia + v_offset + COALESCE(v_coleta, v_corte)) AT TIME ZONE c_tz);
        RETURN NEXT;
        RETURN;
    END LOOP;
END;
$$;


ALTER FUNCTION "public"."proxima_janela_logistica"("p_modalidade_id" integer, "p_integration_id" integer, "p_agora" timestamp with time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."proxima_janela_logistica"("p_modalidade_id" integer, "p_integration_id" integer, "p_agora" timestamp with time zone) IS 'Proximo corte e proxima coleta de uma modalidade FIXO nesta conta, sempre no futuro e respeitando dias_semana. Calculado na leitura: uma janela diaria recorrente nao pode ser guardada como timestamp.';



CREATE OR REPLACE FUNCTION "public"."public_merchant_store"("_merchant_id" "uuid") RETURNS "jsonb"
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $_$
DECLARE
  v_store JSONB;
BEGIN
  IF to_regclass('public.merchant_profiles') IS NULL
     OR to_regclass('public.merchant_products') IS NULL THEN
    RETURN NULL;
  END IF;

  IF NOT (
    public.is_feature_enabled('merchant_match')
    OR public.is_feature_enabled('commerce')
  ) THEN
    RETURN NULL;
  END IF;

  EXECUTE $query$
    SELECT jsonb_build_object(
      'merchant', jsonb_build_object(
        'id', mp.id,
        'business_name', mp.business_name,
        'phone', mp.phone,
        'city', mp.city,
        'state', mp.state,
        'categories', mp.categories,
        'radius_km', mp.radius_km
      ),
      'products', COALESCE(products.items, '[]'::jsonb)
    )
    FROM public.merchant_profiles mp
    LEFT JOIN LATERAL (
      SELECT jsonb_agg(
        jsonb_build_object(
          'id', p.id,
          'name', p.name,
          'description', p.description,
          'category', p.category,
          'subcategory', p.subcategory,
          'unit', p.unit,
          'price_cents', p.price_cents,
          'min_order_qty', p.min_order_qty,
          'photo_url', p.photo_url
        )
        ORDER BY p.category, p.name
      ) AS items
      FROM public.merchant_products p
      WHERE p.merchant_id = mp.id
        AND p.active = true
    ) products ON true
    WHERE mp.id = $1
      AND mp.active = true
  $query$
  INTO v_store
  USING _merchant_id;

  RETURN v_store;
END;
$_$;


ALTER FUNCTION "public"."public_merchant_store"("_merchant_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validar_gtin"("p_gtin" "text") RETURNS boolean
    LANGUAGE "plpgsql" IMMUTABLE
    AS $_$
DECLARE v text := btrim(p_gtin); soma integer := 0; i integer; digito integer; esperado integer;
BEGIN
 IF v='SEM GTIN' THEN RETURN true; END IF;
 IF v !~ '^[0-9]+$' OR length(v) NOT IN (8,12,13,14) THEN RETURN false; END IF;
 FOR i IN 1..length(v)-1 LOOP
  digito:=substr(v,length(v)-i,1)::integer;
  soma:=soma+digito*CASE WHEN i%2=1 THEN 3 ELSE 1 END;
 END LOOP;
 esperado:=(10-(soma%10))%10;
 RETURN esperado=right(v,1)::integer;
END $_$;


ALTER FUNCTION "public"."validar_gtin"("p_gtin" "text") OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."produtos" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "sku" character varying(100) NOT NULL,
    "descricao" "text",
    "categoria_id" integer,
    "tags" "text"[],
    "atributos" "jsonb",
    "precificacao" "jsonb",
    "dados_estoque" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "preco_custo" numeric(10,4),
    "preco_venda" numeric(10,4),
    "estoque_minimo" integer DEFAULT 0,
    "estoque_maximo" integer DEFAULT 0,
    "tipo_material" character varying(50),
    "unidade_medida_id" integer,
    "sku_pai" character varying(100),
    "parent_id" integer,
    "status" character varying(20) DEFAULT 'ativo'::character varying,
    "formato" "text" DEFAULT 'simples'::"text",
    "herdar_dados_pai" boolean DEFAULT true,
    "herdar_bom_pai" boolean DEFAULT true,
    "setor_responsavel_id" integer,
    "estoque_seguranca_dias" integer DEFAULT 0,
    "ponto_ressuprimento" numeric(10,4),
    "lote_economico" numeric(10,4),
    "curva_abc" character varying(1),
    "tipo_produto" "public"."tipo_produto_enum" DEFAULT 'MATERIA_PRIMA'::"public"."tipo_produto_enum",
    "personalizado" boolean DEFAULT false,
    "tag_impressao_pdf" character varying(255),
    "estagio" "public"."estagio_produto" DEFAULT 'RASCUNHO'::"public"."estagio_produto" NOT NULL,
    "combinacao_chave" "text",
    "arte_confirmada_em" timestamp with time zone,
    "arte_confirmada_por" "uuid",
    "ncm" character varying(8),
    "cest" character varying(7),
    "origem_mercadoria" smallint,
    "cfop_padrao_venda" character varying(4),
    "gtin" character varying(14),
    "gtin_embalagem" character varying(14),
    "marca" "text",
    "fabricante" "text",
    "mpn" "text",
    "peso_liquido" numeric(15,6),
    "peso_bruto" numeric(15,6),
    "comprimento" numeric(15,6),
    "largura" numeric(15,6),
    "altura" numeric(15,6),
    "garantia_meses" integer,
    "perfil_fiscal_id" integer,
    "origem_fiscal" "text" DEFAULT 'interno'::"text" NOT NULL,
    CONSTRAINT "produtos_fiscal_dimensoes_ck" CHECK (((("ncm" IS NULL) OR (("ncm")::"text" ~ '^[0-9]{8}$'::"text")) AND (("cest" IS NULL) OR (("cest")::"text" ~ '^[0-9]{7}$'::"text")) AND (("origem_mercadoria" IS NULL) OR (("origem_mercadoria" >= 0) AND ("origem_mercadoria" <= 8))) AND (("gtin" IS NULL) OR "public"."validar_gtin"(("gtin")::"text")) AND (("gtin_embalagem" IS NULL) OR "public"."validar_gtin"(("gtin_embalagem")::"text")) AND (("peso_liquido" IS NULL) OR ("peso_liquido" >= (0)::numeric)) AND (("peso_bruto" IS NULL) OR ("peso_bruto" >= (0)::numeric)) AND (("comprimento" IS NULL) OR ("comprimento" >= (0)::numeric)) AND (("largura" IS NULL) OR ("largura" >= (0)::numeric)) AND (("altura" IS NULL) OR ("altura" >= (0)::numeric)) AND (("garantia_meses" IS NULL) OR ("garantia_meses" >= 0)))),
    CONSTRAINT "produtos_origem_fiscal_ck" CHECK (("origem_fiscal" = ANY (ARRAY['interno'::"text", 'espelho_bling'::"text"]))),
    CONSTRAINT "produtos_status_estagio_ck" CHECK (((("status")::"text" <> 'ativo'::"text") OR ("estagio" = 'PUBLICADO'::"public"."estagio_produto")))
);


ALTER TABLE "public"."produtos" OWNER TO "postgres";


COMMENT ON COLUMN "public"."produtos"."preco_custo" IS 'Preço de custo do produto (normalizado de precificacao.cost_price)';



COMMENT ON COLUMN "public"."produtos"."preco_venda" IS 'Preço de venda do produto (normalizado de precificacao.price)';



COMMENT ON COLUMN "public"."produtos"."estoque_minimo" IS 'Estoque mínimo desejado (normalizado de dados_estoque.stock_min)';



COMMENT ON COLUMN "public"."produtos"."estoque_maximo" IS 'Estoque máximo permitido (normalizado de dados_estoque.stock_max)';



COMMENT ON COLUMN "public"."produtos"."tipo_material" IS 'Tipo de material do produto (normalizado de atributos.material_type)';



COMMENT ON COLUMN "public"."produtos"."unidade_medida_id" IS 'Referência para unidade de medida (normalizado de atributos.unit_of_measure_id)';



COMMENT ON COLUMN "public"."produtos"."sku_pai" IS 'SKU do produto pai para produtos componentes em BOM';



COMMENT ON COLUMN "public"."produtos"."status" IS 'Status do produto (ativo, inativo, rascunho, etc.)';



COMMENT ON COLUMN "public"."produtos"."tipo_produto" IS 'Classificação do produto: MATERIA_PRIMA (pode ficar negativo), INTERMEDIARIO (nunca negativo), PRODUTO_ACABADO (nunca negativo)';



COMMENT ON COLUMN "public"."produtos"."origem_fiscal" IS 'Fonte dos dados fiscais: interno ou espelho_bling';



CREATE OR REPLACE FUNCTION "public"."publicar_produto"("p_produto_id" integer) RETURNS "public"."produtos"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public'
    AS $$ DECLARE r record; atualizado public.produtos; BEGIN SELECT * INTO r FROM public.produto_prontidao(p_produto_id); IF NOT FOUND THEN RAISE EXCEPTION 'Produto % não encontrado',p_produto_id; END IF; IF cardinality(r.pendencias)>0 THEN RAISE EXCEPTION 'Produto não pode ser publicado: %',array_to_string(r.pendencias,', '); END IF; UPDATE public.produtos SET status='ativo',estagio='PUBLICADO',updated_at=now() WHERE id=p_produto_id RETURNING * INTO atualizado; RETURN atualizado; END $$;


ALTER FUNCTION "public"."publicar_produto"("p_produto_id" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."purgar_logs_retencao"() RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_corte_1d  timestamptz := now() - interval '1 day';
    v_corte_7d  timestamptz := now() - interval '7 days';
    v_marcador  jsonb       := '{"_purgado_retencao": true}'::jsonb;
    v_ingest    bigint; v_task bigint; v_att bigint;
    v_we_nulos  bigint; v_we_del bigint; v_mot bigint;
BEGIN
    PERFORM public.rollup_ingest_daily(v_corte_1d);
    PERFORM public.rollup_task_daily(v_corte_1d);
    PERFORM public.rollup_webhook_daily(v_corte_1d);

    DELETE FROM public.pedido_ingest_log WHERE created_at < v_corte_1d;
    GET DIAGNOSTICS v_ingest = ROW_COUNT;

    DELETE FROM public.task_execution_logs WHERE created_at < v_corte_1d;
    GET DIAGNOSTICS v_task = ROW_COUNT;

    DELETE FROM public.webhook_event_attempts WHERE created_at < v_corte_1d;
    GET DIAGNOSTICS v_att = ROW_COUNT;

    -- webhook_events: payload some em 24h, identidade fica 7 dias
    -- (dedupe_key, payload_hash e delivery_count seguem intactos).
    UPDATE public.webhook_events
       SET raw_payload = v_marcador, raw_body = NULL
     WHERE received_at < v_corte_1d
       AND raw_payload <> v_marcador;
    GET DIAGNOSTICS v_we_nulos = ROW_COUNT;

    DELETE FROM public.webhook_events WHERE received_at < v_corte_7d;
    GET DIAGNOSTICS v_we_del = ROW_COUNT;

    -- provider_state so faz sentido na ultima transicao de cada pedido.
    UPDATE public.marketplace_order_transitions t
       SET provider_state = NULL
     WHERE t.provider_state IS NOT NULL
       AND t.created_at < v_corte_1d
       AND t.pedido_id IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.marketplace_order_transitions t2
                    WHERE t2.pedido_id = t.pedido_id
                      AND t2.created_at > t.created_at);
    GET DIAGNOSTICS v_mot = ROW_COUNT;

    RETURN jsonb_build_object(
        'executado_em',               now(),
        'ingest_log_removidos',       v_ingest,
        'task_logs_removidos',        v_task,
        'webhook_attempts_removidos', v_att,
        'webhook_payloads_purgados',  v_we_nulos,
        'webhook_events_removidos',   v_we_del,
        'transitions_state_zerados',  v_mot
    );
END; $$;


ALTER FUNCTION "public"."purgar_logs_retencao"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."purgar_logs_retencao"() IS 'Politica de retencao D1: agrega e depois apaga. Log bruto 1 dia; webhook_events 7 dias sem payload.';



CREATE OR REPLACE FUNCTION "public"."purgar_logs_retencao"("p_lote" integer DEFAULT 20000) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_corte_1d  timestamptz := now() - interval '1 day';
    v_corte_7d  timestamptz := now() - interval '7 days';
    v_marcador  jsonb       := '{"_purgado_retencao": true}'::jsonb;
    v_ingest    bigint; v_task bigint; v_att bigint;
    v_we_purg   bigint; v_we_del bigint; v_mot bigint;
    v_chat_grp  bigint; v_chat bigint;
BEGIN
    PERFORM public.rollup_ingest_daily(v_corte_1d);
    PERFORM public.rollup_task_daily(v_corte_1d);
    PERFORM public.rollup_webhook_daily(v_corte_1d);

    WITH alvo AS (
        SELECT id FROM public.pedido_ingest_log
         WHERE created_at < v_corte_1d LIMIT p_lote
    )
    DELETE FROM public.pedido_ingest_log l USING alvo a WHERE l.id = a.id;
    GET DIAGNOSTICS v_ingest = ROW_COUNT;

    WITH alvo AS (
        SELECT id FROM public.task_execution_logs
         WHERE created_at < v_corte_1d LIMIT p_lote
    )
    DELETE FROM public.task_execution_logs l USING alvo a WHERE l.id = a.id;
    GET DIAGNOSTICS v_task = ROW_COUNT;

    WITH alvo AS (
        SELECT id FROM public.webhook_event_attempts
         WHERE created_at < v_corte_1d LIMIT p_lote
    )
    DELETE FROM public.webhook_event_attempts l USING alvo a WHERE l.id = a.id;
    GET DIAGNOSTICS v_att = ROW_COUNT;

    UPDATE public.webhook_events
       SET raw_payload = v_marcador, raw_body = NULL
     WHERE received_at < v_corte_1d
       AND raw_payload <> v_marcador;
    GET DIAGNOSTICS v_we_purg = ROW_COUNT;

    WITH alvo AS (
        SELECT id FROM public.webhook_events
         WHERE received_at < v_corte_7d LIMIT p_lote
    )
    DELETE FROM public.webhook_events w USING alvo a WHERE w.id = a.id;
    GET DIAGNOSTICS v_we_del = ROW_COUNT;

    -- Chat Shopee: 7 dias. Primeiro o vinculo, depois a mensagem.
    WITH alvo AS (
        SELECT id FROM public.mensagem_chat_shopee
         WHERE created_at < v_corte_7d LIMIT p_lote
    )
    DELETE FROM public.grupo_mensagens_chat_shopee g
     USING alvo a WHERE g.event_id = a.id;
    GET DIAGNOSTICS v_chat_grp = ROW_COUNT;

    WITH alvo AS (
        SELECT id FROM public.mensagem_chat_shopee
         WHERE created_at < v_corte_7d LIMIT p_lote
    )
    DELETE FROM public.mensagem_chat_shopee m USING alvo a WHERE m.id = a.id;
    GET DIAGNOSTICS v_chat = ROW_COUNT;

    UPDATE public.marketplace_order_transitions t
       SET provider_state = v_marcador
     WHERE t.provider_state <> v_marcador
       AND t.created_at < v_corte_1d
       AND t.pedido_id IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.marketplace_order_transitions t2
                    WHERE t2.pedido_id = t.pedido_id
                      AND t2.created_at > t.created_at);
    GET DIAGNOSTICS v_mot = ROW_COUNT;

    RETURN jsonb_build_object(
        'executado_em',               now(),
        'ingest_log_removidos',       v_ingest,
        'task_logs_removidos',        v_task,
        'webhook_attempts_removidos', v_att,
        'webhook_payloads_purgados',  v_we_purg,
        'webhook_events_removidos',   v_we_del,
        'chat_vinculos_removidos',    v_chat_grp,
        'chat_mensagens_removidas',   v_chat,
        'transitions_state_purgados', v_mot
    );
END; $$;


ALTER FUNCTION "public"."purgar_logs_retencao"("p_lote" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."purgar_logs_retencao"("p_lote" integer) IS 'Retencao D1: agrega em *_daily_stats e depois apaga. Log bruto 1 dia; webhook_events 7 dias sem payload. Idempotente e em lotes.';



CREATE OR REPLACE FUNCTION "public"."reclassificar_modalidade_backlog"("p_limite" integer DEFAULT 1000) RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_id    integer;
    v_total integer := 0;
BEGIN
    FOR v_id IN
        SELECT p.id
          FROM public.pedidos p
         WHERE p.despachado_em IS NULL
           AND p.metodo_envio_chave IS NOT NULL
           AND p.modalidade_logistica_id IS NULL
         ORDER BY p.id
         LIMIT p_limite
    LOOP
        PERFORM public.classificar_pedido_modalidade(v_id);
        v_total := v_total + 1;
    END LOOP;

    RETURN v_total;
END;
$$;


ALTER FUNCTION "public"."reclassificar_modalidade_backlog"("p_limite" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."reclassificar_modalidade_backlog"("p_limite" integer) IS 'Reclassifica apenas pedidos abertos. Pedido ja despachado nunca e tocado: alterar o passado quebraria a rastreabilidade do lote e o compromisso ja gravado. Chamar em lotes; pedidos historico e grande.';



CREATE OR REPLACE FUNCTION "public"."reconciliar_item_estoque"("p_item_id" integer, "p_demanda_id" integer, "p_movimentos" "jsonb", "p_snapshot" "jsonb", "p_correlation_id" "uuid", "p_user_id" character varying) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $_$
DECLARE
    v_movimento JSONB;
    v_produto_id INTEGER;
    v_quantidade NUMERIC;
    v_tipo_movimentacao VARCHAR(50);
    v_saldo_antes NUMERIC;
    v_saldo_depois NUMERIC;
    v_mov_id INTEGER;
    v_produto_nome VARCHAR(255);
    v_demanda_nome VARCHAR(255);
    v_usuario_id INTEGER;
    v_estagio VARCHAR(50);
    v_movimentos_resp JSONB := '[]'::JSONB;
BEGIN
    -- Coercao segura de p_user_id (VARCHAR) para INTEGER da FK usuarios.id.
    IF p_user_id IS NOT NULL AND p_user_id ~ '^-?\d+$' THEN
        BEGIN
            v_usuario_id := p_user_id::INTEGER;
        EXCEPTION WHEN OTHERS THEN
            v_usuario_id := NULL;
        END;
    ELSE
        v_usuario_id := NULL;
    END IF;

    -- Buscar nome humano da demanda
    IF p_demanda_id IS NOT NULL THEN
        SELECT descricao INTO v_demanda_nome
          FROM demandas_producao
         WHERE id = p_demanda_id;
    END IF;

    FOR v_movimento IN SELECT * FROM jsonb_array_elements(p_movimentos) LOOP
        v_produto_id := (v_movimento->>'produto_id')::INTEGER;
        v_quantidade := (v_movimento->>'quantidade')::NUMERIC;
        v_tipo_movimentacao := v_movimento->>'tipo';
        v_estagio := v_movimento->>'estagio';

        SELECT nome INTO v_produto_nome
          FROM produtos
         WHERE id = v_produto_id;

        SELECT saldo_atual INTO v_saldo_antes
          FROM estoque_atual
         WHERE produto_id = v_produto_id
           AND deposito_id = (v_movimento->>'deposito_id')::INTEGER
        FOR UPDATE;

        IF v_saldo_antes IS NULL THEN
            v_saldo_antes := 0;
            INSERT INTO estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_produto_id, (v_movimento->>'deposito_id')::INTEGER, v_quantidade, NOW());
            v_saldo_depois := v_quantidade;
        ELSE
            v_saldo_depois := v_saldo_antes + v_quantidade;
            UPDATE estoque_atual
               SET saldo_atual = v_saldo_depois, ultima_atualizacao = NOW(), updated_at = NOW()
             WHERE produto_id = v_produto_id
               AND deposito_id = (v_movimento->>'deposito_id')::INTEGER;
        END IF;

        -- INSERT em movimentacoes_estoque agora inclui estagio.
        INSERT INTO movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            documento_referencia, correlation_id, origem_tipo, data_movimentacao,
            item_demanda_id, produto_nome, demanda_nome, estagio
        ) VALUES (
            v_produto_id, (v_movimento->>'deposito_id')::INTEGER, v_tipo_movimentacao, v_quantidade,
            v_saldo_antes, v_saldo_depois, v_movimento->>'motivo', v_usuario_id,
            CASE WHEN v_usuario_id IS NULL THEN 'caller=' || COALESCE(p_user_id, 'NULL') ELSE NULL END,
            p_correlation_id, NULL, NOW(),
            p_item_id, v_produto_nome, v_demanda_nome, v_estagio
        ) RETURNING id INTO v_mov_id;

        IF p_item_id IS NOT NULL AND p_demanda_id IS NOT NULL THEN
            INSERT INTO demanda_estoque_processado (
                item_id, demanda_id, estagio, quantidade, correlation_id,
                saldo_acumulado, produto_id, tipo_movimentacao, created_at
            ) VALUES (
                p_item_id, p_demanda_id, v_estagio, v_quantidade,
                p_correlation_id, v_saldo_depois, v_produto_id, v_tipo_movimentacao, NOW()
            )
            ON CONFLICT (item_id, estagio, correlation_id, produto_id, tipo_movimentacao)
                WHERE correlation_id IS NOT NULL
            DO UPDATE SET
                quantidade      = demanda_estoque_processado.quantidade + EXCLUDED.quantidade,
                saldo_acumulado = EXCLUDED.saldo_acumulado,
                updated_at      = NOW();
        END IF;

        v_movimentos_resp := v_movimentos_resp || jsonb_build_array(jsonb_build_object(
            'movimento_id', v_mov_id,
            'produto_id', v_produto_id,
            'quantidade', v_quantidade,
            'tipo', v_tipo_movimentacao,
            'estagio', v_estagio
        ));
    END LOOP;

    RETURN jsonb_build_object(
        'sucesso', true,
        'movimentos', v_movimentos_resp,
        'erros', '[]'::JSONB,
        'snapshot_id', NULL,
        'item_id', p_item_id,
        'demanda_id', p_demanda_id,
        'correlation_id', p_correlation_id
    );

EXCEPTION
    WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'sucesso', false,
            'erro', SQLERRM,
            'sqlstate', SQLSTATE,
            'item_id', p_item_id,
            'demanda_id', p_demanda_id,
            'correlation_id', p_correlation_id
        );
END;
$_$;


ALTER FUNCTION "public"."reconciliar_item_estoque"("p_item_id" integer, "p_demanda_id" integer, "p_movimentos" "jsonb", "p_snapshot" "jsonb", "p_correlation_id" "uuid", "p_user_id" character varying) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."reconciliar_item_estoque"("p_item_id" integer, "p_demanda_id" integer, "p_movimentos" "jsonb", "p_snapshot" "jsonb", "p_correlation_id" "uuid", "p_user_id" character varying) IS 'RPC atomica do motor de reconciliacao. Grava estagio em movimentacoes_estoque para permitir agrupamento por sub-arvore BOM na view view_movimentacoes_consolidadas.';



CREATE OR REPLACE FUNCTION "public"."registrar_alteracao_sku"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF NEW.sku IS DISTINCT FROM OLD.sku THEN
    INSERT INTO public.produto_sku_historico
      (produto_id, sku_anterior, sku_novo, alterado_por)
    VALUES (NEW.id, OLD.sku, NEW.sku, auth.uid());
    INSERT INTO public.produtos_externos (produto_id, codigo_externo, tipo, plataforma, metadados)
    SELECT OLD.id, OLD.sku, 'SKU', NULL, jsonb_build_object('origem', 'historico_sku')
    WHERE NOT EXISTS (
      SELECT 1 FROM public.produtos_externos
       WHERE produto_id = OLD.id AND codigo_externo = OLD.sku AND tipo = 'SKU'
    );
  END IF;
  RETURN NEW;
END $$;


ALTER FUNCTION "public"."registrar_alteracao_sku"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."registrar_metodo_envio_observado"("p_module_id" character varying, "p_integration_id" integer, "p_campo_origem" character varying, "p_chave" "text", "p_rotulo" "text", "p_pedido_id" integer DEFAULT NULL::integer) RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_id integer;
BEGIN
    IF p_chave IS NULL OR btrim(p_chave) = '' THEN
        RETURN NULL;
    END IF;

    INSERT INTO public.metodos_envio_observados (
        module_id, integration_id, campo_origem,
        valor_bruto, valor_normalizado, rotulo_bruto, pedido_exemplo_id
    )
    VALUES (
        p_module_id, p_integration_id, p_campo_origem,
        p_chave, lower(btrim(p_chave)), p_rotulo, p_pedido_id
    )
    ON CONFLICT (module_id, campo_origem, valor_normalizado) DO UPDATE
       SET ocorrencias          = public.metodos_envio_observados.ocorrencias + 1,
           ultima_ocorrencia_em = now(),
           rotulo_bruto         = COALESCE(EXCLUDED.rotulo_bruto,
                                           public.metodos_envio_observados.rotulo_bruto)
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;


ALTER FUNCTION "public"."registrar_metodo_envio_observado"("p_module_id" character varying, "p_integration_id" integer, "p_campo_origem" character varying, "p_chave" "text", "p_rotulo" "text", "p_pedido_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."registrar_metodo_envio_observado"("p_module_id" character varying, "p_integration_id" integer, "p_campo_origem" character varying, "p_chave" "text", "p_rotulo" "text", "p_pedido_id" integer) IS 'Upsert pela chave normalizada. Nao emite alerta: a emissao e do worker, que le status = NOVO e alerta_emitido_em IS NULL, para nao alertar dentro de transacao de ingest.';



CREATE OR REPLACE FUNCTION "public"."registrar_movimentacao_primaria"("p_produto_id" integer, "p_deposito_id" integer, "p_tipo_movimentacao" character varying, "p_quantidade" numeric, "p_motivo" "text", "p_origem_tipo" integer, "p_usuario_id" integer, "p_documento_referencia" character varying DEFAULT NULL::character varying, "p_correlation_id" "uuid" DEFAULT "gen_random_uuid"()) RETURNS "uuid"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_saldo_atual NUMERIC(15,4);
    v_saldo_novo NUMERIC(15,4);
    v_mov_id INTEGER;
BEGIN
    -- 1. Obter e atualizar saldo na estoque_atual
    SELECT saldo_atual INTO v_saldo_atual
    FROM public.estoque_atual
    WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id
    FOR UPDATE;

    IF v_saldo_atual IS NULL THEN
        v_saldo_atual := 0;
        INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
        VALUES (p_produto_id, p_deposito_id, p_quantidade, NOW());
        v_saldo_novo := p_quantidade;
    ELSE
        v_saldo_novo := v_saldo_atual + p_quantidade;
        UPDATE public.estoque_atual
        SET saldo_atual = v_saldo_novo, ultima_atualizacao = NOW(), updated_at = NOW()
        WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id;
    END IF;

    -- 2. Inserir na movimentacoes_estoque
    INSERT INTO public.movimentacoes_estoque (
        produto_id, deposito_id, tipo_movimentacao, quantidade,
        saldo_antes, saldo_depois, motivo, usuario_id,
        documento_referencia, correlation_id, origem_tipo, data_movimentacao
    ) VALUES (
        p_produto_id, p_deposito_id, p_tipo_movimentacao, p_quantidade,
        v_saldo_atual, v_saldo_novo, p_motivo, p_usuario_id,
        p_documento_referencia, p_correlation_id, p_origem_tipo, NOW()
    ) RETURNING id INTO v_mov_id;

    -- 3. (removido no Sprint 5) O passo que enfileirava CONSUMO_BOM/ESTORNO_BOM
    --    em fila_processamento_estoque saiu junto com o motor legado.

    RETURN p_correlation_id;
END;
$$;


ALTER FUNCTION "public"."registrar_movimentacao_primaria"("p_produto_id" integer, "p_deposito_id" integer, "p_tipo_movimentacao" character varying, "p_quantidade" numeric, "p_motivo" "text", "p_origem_tipo" integer, "p_usuario_id" integer, "p_documento_referencia" character varying, "p_correlation_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."registrar_saida_coleta_demanda"("p_demanda_id" integer, "p_user_id" "text" DEFAULT 'System'::"text") RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $_$
DECLARE
    v_status       text;
    v_deposito     int;
    v_correlation  uuid := gen_random_uuid();
    v_usuario_id   int;
    v_ja           int;
    v_item         record;
    v_saldo_antes  numeric;
    v_saldo_depois numeric;
    v_linhas       int := 0;
    v_total        numeric := 0;
    v_finalizados  int := 0;
    v_ids_a_reconciliar int[];
    v_sem_produto  int := 0;
BEGIN
    SELECT status INTO v_status FROM public.demandas_producao WHERE id = p_demanda_id;
    IF v_status IS NULL THEN
        RETURN jsonb_build_object('ok', false, 'motivo', 'demanda_inexistente');
    END IF;

    IF v_status <> 'COLETADO' THEN
        RETURN jsonb_build_object('ok', false, 'motivo', 'demanda_nao_coletada', 'status', v_status);
    END IF;

    SELECT COALESCE(array_agg(id), ARRAY[]::int[]) INTO v_ids_a_reconciliar
      FROM public.itens_demanda
     WHERE demanda_id = p_demanda_id
       AND COALESCE(quantidade, 0) > 0
       AND COALESCE(finalizados_qtd, 0) < COALESCE(quantidade, 0)
       AND produto_id IS NOT NULL;

    WITH finalizados AS (
        UPDATE public.itens_demanda
           SET finalizados_qtd = COALESCE(quantidade, 0),
               status_item     = 'Concluído',
               updated_at      = now()
         WHERE demanda_id = p_demanda_id
           AND COALESCE(quantidade, 0) > 0
           AND (
                COALESCE(finalizados_qtd, 0) < COALESCE(quantidade, 0)
                OR status_item IS DISTINCT FROM 'Concluído'
               )
        RETURNING id
    )
    SELECT count(*) INTO v_finalizados FROM finalizados;

    IF COALESCE(array_length(v_ids_a_reconciliar, 1), 0) > 0 THEN
        UPDATE public.itens_demanda
           SET status_processamento = 'PENDENTE'
         WHERE id = ANY(v_ids_a_reconciliar);

        INSERT INTO public.eventos_producao_v2 (
            item_demanda_id, demanda_id, estagio, quantidade_reportada,
            tipo_evento, processado, correlation_id, created_at
        )
        SELECT i.id, p_demanda_id, 'finalizados_qtd', COALESCE(i.quantidade, 0),
               'LIQUIDACAO', false, v_correlation, now()
          FROM public.itens_demanda i
         WHERE i.id = ANY(v_ids_a_reconciliar);
    END IF;

    SELECT count(*) INTO v_ja
      FROM public.movimentacoes_estoque m
      JOIN public.itens_demanda i ON i.id = m.item_demanda_id
     WHERE i.demanda_id = p_demanda_id AND m.tipo_movimentacao = 'SAIDA_COLETA';

    SELECT count(*) INTO v_sem_produto
      FROM public.itens_demanda
     WHERE demanda_id = p_demanda_id AND produto_id IS NULL;

    IF v_ja > 0 THEN
        RETURN jsonb_build_object(
            'ok', true,
            'motivo', 'ja_registrada',
            'demanda_id', p_demanda_id,
            'movimentos_existentes', v_ja,
            'itens_finalizados', v_finalizados,
            'itens_sem_produto_mapeado', v_sem_produto
        );
    END IF;

    SELECT COALESCE((SELECT (valor #>> '{}')::int FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_default_production_deposit_id'),
                    (SELECT id FROM public.depositos ORDER BY id LIMIT 1), 1)
      INTO v_deposito;

    v_usuario_id := CASE WHEN p_user_id ~ '^-?\d+$' THEN p_user_id::int ELSE NULL END;

    FOR v_item IN
        SELECT i.id AS item_id, i.produto_id, p.nome AS produto_nome,
               COALESCE(i.quantidade, 0)::numeric AS qtd_demandada
          FROM public.itens_demanda i
          JOIN public.produtos p ON p.id = i.produto_id
         WHERE i.demanda_id = p_demanda_id
           AND i.produto_id IS NOT NULL
           AND COALESCE(i.quantidade, 0) > 0
    LOOP
        SELECT saldo_atual INTO v_saldo_antes
          FROM public.estoque_atual
         WHERE produto_id = v_item.produto_id AND deposito_id = v_deposito
         FOR UPDATE;

        IF v_saldo_antes IS NULL THEN
            v_saldo_antes := 0;
            INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_item.produto_id, v_deposito, -v_item.qtd_demandada, now());
            v_saldo_depois := -v_item.qtd_demandada;
        ELSE
            v_saldo_depois := v_saldo_antes - v_item.qtd_demandada;
            UPDATE public.estoque_atual
               SET saldo_atual = v_saldo_depois, ultima_atualizacao = now(), updated_at = now()
             WHERE produto_id = v_item.produto_id AND deposito_id = v_deposito;
        END IF;

        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            correlation_id, data_movimentacao, item_demanda_id, produto_nome, estagio
        ) VALUES (
            v_item.produto_id, v_deposito, 'SAIDA_COLETA', -v_item.qtd_demandada,
            v_saldo_antes, v_saldo_depois,
            'Saída por coleta completa da demanda ' || p_demanda_id, v_usuario_id,
            v_correlation, now(), v_item.item_id, v_item.produto_nome, 'coleta'
        );

        INSERT INTO public.demanda_estoque_processado (
            item_id, demanda_id, estagio, quantidade, correlation_id,
            saldo_acumulado, produto_id, tipo_movimentacao, created_at
        ) VALUES (
            v_item.item_id, p_demanda_id, 'coleta', -v_item.qtd_demandada, v_correlation,
            v_saldo_depois, v_item.produto_id, 'SAIDA_COLETA', now()
        )
        ON CONFLICT (item_id, estagio, correlation_id, produto_id, tipo_movimentacao)
            WHERE correlation_id IS NOT NULL
        DO NOTHING;

        v_linhas := v_linhas + 1;
        v_total  := v_total + v_item.qtd_demandada;
    END LOOP;

    RETURN jsonb_build_object(
        'ok', true,
        'demanda_id', p_demanda_id,
        'correlation_id', v_correlation,
        'itens_finalizados', v_finalizados,
        'itens_baixados', v_linhas,
        'quantidade_total', v_total,
        'itens_sem_produto_mapeado', v_sem_produto
    );
END; $_$;


ALTER FUNCTION "public"."registrar_saida_coleta_demanda"("p_demanda_id" integer, "p_user_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."registrar_saida_coleta_demanda"("p_demanda_id" integer, "p_user_id" "text") IS 'QA-5: coleta completa da saida em TODOS os itens da demanda, pela quantidade demandada, e corrige retroativamente a producao que ficou para tras — emitindo LIQUIDACAO para o motor reconciliar o delta. Idempotente; recusa demanda fora de COLETADO.';



CREATE TABLE IF NOT EXISTS "public"."regras_logisticas_integracao" (
    "id" bigint NOT NULL,
    "marketplace_integration_id" integer NOT NULL,
    "modalidade" character varying(50) NOT NULL,
    "tipo_envio" character varying(50) NOT NULL,
    "horario_limite" time without time zone,
    "ponto_coleta_id" integer,
    "dias_semana" smallint[] DEFAULT ARRAY[1, 2, 3, 4, 5, 6, 7],
    "prioridade_uso" integer DEFAULT 1,
    "ativo" boolean DEFAULT true,
    "descricao" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "horario_corte" time without time zone,
    "horario_coleta" time without time zone,
    "modalidade_id" integer,
    "coleta_dia_offset" smallint DEFAULT 0 NOT NULL,
    "offset_etiqueta_min" integer,
    "offset_coleta_min" integer,
    CONSTRAINT "regras_logisticas_integracao_forma_ck" CHECK (((("horario_corte" IS NOT NULL) AND ("horario_coleta" IS NOT NULL)) OR (("horario_corte" IS NOT NULL) AND (("tipo_envio")::"text" = 'PONTO_COLETA'::"text") AND ("ponto_coleta_id" IS NOT NULL)) OR (("offset_etiqueta_min" IS NOT NULL) AND ("offset_coleta_min" IS NOT NULL)))),
    CONSTRAINT "regras_logisticas_integracao_tipo_envio_check" CHECK ((("tipo_envio")::"text" = ANY ((ARRAY['COLETA_LOCAL'::character varying, 'PONTO_COLETA'::character varying])::"text"[])))
);


ALTER TABLE "public"."regras_logisticas_integracao" OWNER TO "postgres";


COMMENT ON TABLE "public"."regras_logisticas_integracao" IS 'Regras logisticas canonicas por instancia marketplace instalada.';



COMMENT ON COLUMN "public"."regras_logisticas_integracao"."dias_semana" IS 'Dias validos para a regra (1=segunda ... 7=domingo).';



COMMENT ON COLUMN "public"."regras_logisticas_integracao"."horario_corte" IS 'Hora limite do pagamento para entrar na coleta do mesmo dia.';



COMMENT ON COLUMN "public"."regras_logisticas_integracao"."horario_coleta" IS 'Hora da saida. Para COLETA_LOCAL e quando a transportadora passa. Para PONTO_COLETA fica NULO no caso normal e a hora vem de pontos_coleta.horario_fechamento — preencher aqui e excecao, para um dia em que o ponto fecha mais cedo.';



COMMENT ON COLUMN "public"."regras_logisticas_integracao"."modalidade_id" IS 'Fonte de verdade da modalidade. A coluna `modalidade` (texto) e projecao mantida por trigger, apenas para os consumidores legados.';



COMMENT ON COLUMN "public"."regras_logisticas_integracao"."offset_etiqueta_min" IS 'Prazo de etiqueta em minutos apos a venda, para modalidade RELATIVO. E o "corte" dessa modalidade.';



COMMENT ON COLUMN "public"."regras_logisticas_integracao"."offset_coleta_min" IS 'Prazo de coleta em minutos apos a venda, para modalidade RELATIVO.';



CREATE OR REPLACE FUNCTION "public"."regras_da_modalidade"("p_modalidade_id" integer, "p_integration_id" integer) RETURNS SETOF "public"."regras_logisticas_integracao"
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT r.*
      FROM public.regras_logisticas_integracao r
      JOIN public.regra_logistica_modalidades rm ON rm.regra_id = r.id
     WHERE r.ativo
       AND rm.modalidade_id = p_modalidade_id
       AND r.marketplace_integration_id = p_integration_id;
$$;


ALTER FUNCTION "public"."regras_da_modalidade"("p_modalidade_id" integer, "p_integration_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."regras_da_modalidade"("p_modalidade_id" integer, "p_integration_id" integer) IS 'Janelas ativas que atendem uma modalidade numa conta. Definicao unica de membresia: janelas_logisticas, coleta_do_pedido e proxima_janela_logistica leem daqui em vez de repetir o predicado.';



CREATE OR REPLACE FUNCTION "public"."repair_personalized_classification"("p_pedido_ids" bigint[] DEFAULT NULL::bigint[], "p_source" "text" DEFAULT 'shopee'::"text") RETURNS TABLE("matched_items" integer, "updated_items" integer, "updated_orders" integer, "updated_bling_orders" integer)
    LANGUAGE "plpgsql"
    AS $$
declare
    v_matched_items integer := 0;
    v_updated_items integer := 0;
    v_updated_orders integer := 0;
    v_updated_bling_orders integer := 0;
begin
    with candidate_items as (
        select
            ip.id as item_id,
            p.id as pedido_id,
            p.pedido_bling_id,
            position('personaliz' in lower(coalesce(ip.descricao, ''))) > 0 as should_be_personalized
        from public.itens_pedido ip
        join public.pedidos p on p.id = ip.pedido_id
        left join public.canais_venda cv on cv.id = p.canal_venda_id
        where (p_pedido_ids is null or p.id = any(p_pedido_ids))
          and (
              p_source is null
              or lower(coalesce(cv.slug, p.origem, '')) = lower(p_source)
          )
    ),
    updated_item_rows as (
        update public.itens_pedido ip
           set personalizado = ci.should_be_personalized,
               updated_at = now()
          from candidate_items ci
         where ip.id = ci.item_id
           and coalesce(ip.personalizado, false) is distinct from ci.should_be_personalized
        returning ip.id
    ),
    order_flags as (
        select
            ci.pedido_id,
            ci.pedido_bling_id,
            bool_or(ci.should_be_personalized) as should_be_personalized
        from candidate_items ci
        group by ci.pedido_id, ci.pedido_bling_id
    ),
    updated_order_rows as (
        update public.pedidos p
           set personalizado = of.should_be_personalized,
               updated_at = now()
          from order_flags of
         where p.id = of.pedido_id
           and coalesce(p.personalizado, false) is distinct from of.should_be_personalized
        returning p.id
    ),
    updated_bling_rows as (
        update public.pedidos_bling pb
           set personalizado = of.should_be_personalized,
               updated_at = now()
          from order_flags of
         where pb.id = of.pedido_bling_id
           and coalesce(pb.personalizado, false) is distinct from of.should_be_personalized
        returning pb.id
    )
    select
        count(*) filter (where should_be_personalized)::integer,
        (select count(*)::integer from updated_item_rows),
        (select count(*)::integer from updated_order_rows),
        (select count(*)::integer from updated_bling_rows)
    into
        v_matched_items,
        v_updated_items,
        v_updated_orders,
        v_updated_bling_orders
    from candidate_items;

    return query
    select
        coalesce(v_matched_items, 0),
        coalesce(v_updated_items, 0),
        coalesce(v_updated_orders, 0),
        coalesce(v_updated_bling_orders, 0);
end;
$$;


ALTER FUNCTION "public"."repair_personalized_classification"("p_pedido_ids" bigint[], "p_source" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."resolver_compromisso_logistico"("p_modalidade_id" integer, "p_integration_id" integer, "p_data_venda" timestamp with time zone, "p_agora" timestamp with time zone DEFAULT "now"()) RETURNS timestamp with time zone
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    c_tz     constant text := 'America/Sao_Paulo';
    v_tipo   text;
    v_offset integer;
    v_corte  time;
    v_base   date;
    v_result timestamptz;
BEGIN
    IF p_modalidade_id IS NULL THEN
        RETURN COALESCE(p_data_venda, p_agora);
    END IF;

    SELECT ml.tipo_prazo,
           COALESCE(r.offset_etiqueta_min, ml.offset_etiqueta_min),
           COALESCE(r.horario_corte, ml.corte_horario)
      INTO v_tipo, v_offset, v_corte
      FROM public.modalidades_logisticas ml
      LEFT JOIN public.regras_logisticas_integracao r
             ON r.modalidade_id = ml.id
            AND r.marketplace_integration_id = p_integration_id
            AND r.ativo
     WHERE ml.id = p_modalidade_id
     ORDER BY r.prioridade_uso DESC NULLS LAST, r.id
     LIMIT 1;

    IF v_tipo IS NULL THEN
        RETURN COALESCE(p_data_venda, p_agora);
    END IF;

    IF v_tipo = 'RELATIVO' THEN
        -- Ancorado na venda, nunca em now(): o relogio do Turbo comeca quando o
        -- cliente comprou. Reprocessar o pedido amanha nao pode empurrar o
        -- prazo dele para amanha.
        RETURN COALESCE(p_data_venda, p_agora) + make_interval(mins => COALESCE(v_offset, 0));
    END IF;

    v_base   := (p_agora AT TIME ZONE c_tz)::date;
    v_result := ((v_base + v_corte) AT TIME ZONE c_tz);

    IF v_result <= p_agora THEN
        v_result := ((v_base + 1 + v_corte) AT TIME ZONE c_tz);
    END IF;

    RETURN v_result;
END;
$$;


ALTER FUNCTION "public"."resolver_compromisso_logistico"("p_modalidade_id" integer, "p_integration_id" integer, "p_data_venda" timestamp with time zone, "p_agora" timestamp with time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."resolver_compromisso_logistico"("p_modalidade_id" integer, "p_integration_id" integer, "p_data_venda" timestamp with time zone, "p_agora" timestamp with time zone) IS 'Corte por conta vem de regras_logisticas_integracao (aba Logistica); o catalogo e so o default de quem nao tem janela cadastrada.';



CREATE OR REPLACE FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text" DEFAULT NULL::"text") RETURNS integer
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    v_cat_miolo int;
    v_norm      text;
    v_token     text;
    v_achado    int;
BEGIN
    SELECT (valor #>> '{}')::int INTO v_cat_miolo
      FROM public.configuracoes_aplicacao
     WHERE nome = 'producao_miolos_category_id';
    v_cat_miolo := COALESCE(v_cat_miolo, 6);

    -- Espaco e hifen viram '_': o SKU interno usa '_' e a origem varia.
    v_norm := regexp_replace(upper(btrim(COALESCE(p_codigo, ''))), '[\s\-]+', '_', 'g');
    IF v_norm = '' THEN RETURN NULL; END IF;

    FOR v_token IN
        SELECT t FROM (VALUES
            (split_part(v_norm, '_', 1) || '_' || split_part(v_norm, '_', 2)),
            (split_part(v_norm, '_', 1))
        ) AS candidatos(t)
        WHERE t IS NOT NULL AND t <> '' AND t <> '_'
    LOOP
        SELECT mi.id INTO v_achado
          FROM public.produtos mi
         WHERE mi.categoria_id = v_cat_miolo
           AND (
                upper(btrim(mi.sku::text)) = 'MIOLO-' || v_token
             OR upper(btrim(mi.sku::text)) = v_token
             OR EXISTS (SELECT 1 FROM public.produtos_externos pe
                         WHERE pe.produto_id = mi.id
                           AND upper(btrim(pe.codigo_externo)) = v_token
                           AND (pe.plataforma IS NULL
                                OR p_plataforma IS NULL
                                OR lower(pe.plataforma) = lower(p_plataforma)))
           )
         ORDER BY (upper(btrim(mi.sku::text)) = 'MIOLO-' || v_token) DESC
         LIMIT 1;
        IF v_achado IS NOT NULL THEN RETURN v_achado; END IF;
    END LOOP;

    RETURN NULL;
END; $$;


ALTER FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text") IS 'Identifica o miolo pelo prefixo do SKU quando o produto acabado nao resolve. Normaliza espaco e hifen para _, e tenta o codigo de dois segmentos antes do de um (combos). Substitui as funcoes fix_* do consolidador legado por consulta ao cadastro.';



CREATE OR REPLACE FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text" DEFAULT NULL::"text", "p_usar_fallback" boolean DEFAULT true, OUT "miolo_id" integer, OUT "origem" "text") RETURNS "record"
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    v_cat_miolo int;
    v_norm      text;
    v_token     text;
BEGIN
    SELECT (valor #>> '{}')::int INTO v_cat_miolo
      FROM public.configuracoes_aplicacao
     WHERE nome = 'producao_miolos_category_id';
    v_cat_miolo := COALESCE(v_cat_miolo, 6);

    v_norm := regexp_replace(upper(btrim(COALESCE(p_codigo, ''))), '[\s\-]+', '_', 'g');
    IF v_norm = '' THEN RETURN; END IF;

    -- 1. Token exato: dois segmentos (combos) e depois um.
    FOR v_token IN
        SELECT t FROM (VALUES
            (split_part(v_norm, '_', 1) || '_' || split_part(v_norm, '_', 2)),
            (split_part(v_norm, '_', 1))
        ) AS c(t) WHERE t IS NOT NULL AND t <> '' AND t <> '_'
    LOOP
        SELECT mi.id INTO miolo_id
          FROM public.produtos mi
         WHERE mi.categoria_id = v_cat_miolo
           AND (upper(btrim(mi.sku::text)) IN ('MIOLO-' || v_token, v_token)
             OR EXISTS (SELECT 1 FROM public.produtos_externos pe
                         WHERE pe.produto_id = mi.id
                           AND upper(btrim(pe.codigo_externo)) = v_token
                           AND (pe.plataforma IS NULL OR p_plataforma IS NULL
                                OR lower(pe.plataforma) = lower(p_plataforma))))
         ORDER BY (upper(btrim(mi.sku::text)) = 'MIOLO-' || v_token) DESC
         LIMIT 1;
        IF miolo_id IS NOT NULL THEN
            origem := 'cadastro';
            RETURN;
        END IF;
    END LOOP;

    IF NOT p_usar_fallback THEN RETURN; END IF;

    -- 2. Fallback do legado: prefixo decrescente, casamento mais longo vence.
    --    E o equivalente cadastral de apply_miolo_fixes (miolo[:8], miolo[:6]).
    --    Minimo de 4 caracteres para nao casar por acidente.
    v_token := split_part(v_norm, '_', 1);
    SELECT mi.id INTO miolo_id
      FROM public.produtos mi
     WHERE mi.categoria_id = v_cat_miolo
       AND length(replace(upper(btrim(mi.sku::text)), 'MIOLO-', '')) >= 4
       AND v_token LIKE replace(upper(btrim(mi.sku::text)), 'MIOLO-', '') || '%'
     ORDER BY length(replace(upper(btrim(mi.sku::text)), 'MIOLO-', '')) DESC
     LIMIT 1;

    IF miolo_id IS NOT NULL THEN origem := 'fallback_legado'; END IF;
END; $$;


ALTER FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text", "p_usar_fallback" boolean, OUT "miolo_id" integer, OUT "origem" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."resolver_produto_completo"("p_codigo" "text", "p_plataforma" "text" DEFAULT NULL::"text") RETURNS TABLE("produto_id" integer, "produto_sku" "text", "produto_nome" "text", "variacao" "text", "miolo_id" integer, "miolo_sku" "text", "miolo_nome" "text", "origem" "text")
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE v_produto integer; v_fb record;
BEGIN
 v_produto:=public.resolver_produto_por_codigo(p_codigo,p_plataforma);
 IF v_produto IS NOT NULL THEN
  RETURN QUERY SELECT p.id,p.sku::text,p.nome::text,(SELECT o.nome::text FROM public.produto_variacao_valores vv JOIN public.produto_eixos e ON e.id=vv.eixo_id AND e.codigo='estampa' JOIN public.produto_eixo_opcoes o ON o.id=vv.opcao_id WHERE vv.produto_id=p.id LIMIT 1),m.id,m.sku::text,m.nome::text,CASE WHEN EXISTS (SELECT 1 FROM public.produto_variacao_valores vv JOIN public.produto_eixos e ON e.id=vv.eixo_id AND e.codigo='miolo' WHERE vv.produto_id=p.id) THEN 'eixo_cadastrado' ELSE CASE WHEN upper(btrim(p.sku::text))=upper(btrim(p_codigo)) THEN 'sku_interno' ELSE 'apelido' END END::text FROM public.produtos p LEFT JOIN LATERAL (SELECT mi.id,mi.sku,mi.nome FROM public.produto_variacao_valores vv JOIN public.produto_eixos e ON e.id=vv.eixo_id AND e.codigo='miolo' JOIN public.produto_eixo_opcoes o ON o.id=vv.opcao_id JOIN public.produtos mi ON upper(regexp_replace(mi.sku,'^MIOLO-','', 'i'))=o.codigo WHERE vv.produto_id=p.id LIMIT 1) m ON true WHERE p.id=v_produto;
  RETURN;
 END IF;
 SELECT * INTO v_fb FROM public.resolver_miolo_por_prefixo(p_codigo,p_plataforma,true);
 IF v_fb.miolo_id IS NULL THEN RETURN; END IF;
 RETURN QUERY SELECT NULL::integer,NULL::text,NULL::text,NULL::text,mi.id,mi.sku::text,mi.nome::text,('miolo_por_'||v_fb.origem)::text FROM public.produtos mi WHERE mi.id=v_fb.miolo_id;
END $$;


ALTER FUNCTION "public"."resolver_produto_completo"("p_codigo" "text", "p_plataforma" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."resolver_produto_completo"("p_codigo" "text", "p_plataforma" "text") IS 'Identifica produto acabado, variacao e miolo a partir de um codigo de marketplace. Preserva a inteligencia do consolidador legado usando dado cadastrado: SKU interno, apelidos em produtos_externos, ficha tecnica e a categoria de miolo configurada. Quando o produto nao resolve, ainda devolve o miolo pelo prefixo do SKU.';



CREATE OR REPLACE FUNCTION "public"."resolver_produto_por_codigo"("p_codigo" "text", "p_plataforma" "text" DEFAULT NULL::"text") RETURNS integer
    LANGUAGE "sql" STABLE
    AS $$
    WITH alvo AS (SELECT upper(btrim(p_codigo)) AS codigo)
    SELECT produto_id FROM (
        -- 1. SKU interno: o identificador principal da empresa.
        SELECT p.id AS produto_id, 0 AS nivel, 0 AS especifico
          FROM public.produtos p, alvo
         WHERE upper(btrim(p.sku)) = alvo.codigo
        UNION ALL
        -- 2..4. Apelidos externos.
        SELECT pe.produto_id,
               CASE pe.tipo WHEN 'SKU' THEN 1 WHEN 'ID' THEN 2 ELSE 3 END,
               CASE WHEN pe.plataforma IS NOT NULL THEN 0 ELSE 1 END
          FROM public.produtos_externos pe, alvo
         WHERE upper(btrim(pe.codigo_externo)) = alvo.codigo
           AND (pe.plataforma IS NULL
                OR p_plataforma IS NULL
                OR lower(pe.plataforma) = lower(p_plataforma))
    ) candidatos
    WHERE p_codigo IS NOT NULL AND btrim(p_codigo) <> ''
    ORDER BY nivel, especifico
    LIMIT 1;
$$;


ALTER FUNCTION "public"."resolver_produto_por_codigo"("p_codigo" "text", "p_plataforma" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."resolver_produto_por_codigo"("p_codigo" "text", "p_plataforma" "text") IS 'Resolve um codigo de marketplace para produtos.id. Precedencia: SKU interno > apelido SKU > apelido ID > apelido NOME; apelido da plataforma vence apelido geral. Retorna NULL quando nao resolve.';



CREATE OR REPLACE FUNCTION "public"."rollup_ingest_daily"("p_ate" timestamp with time zone DEFAULT "now"()) RETURNS bigint
    LANGUAGE "plpgsql"
    AS $$
DECLARE v_linhas bigint;
BEGIN
    INSERT INTO public.ingest_daily_stats AS d
        (dia, stage, status, total, pedidos_distintos, duracao_ms_media, duracao_ms_max)
    SELECT created_at::date,
           COALESCE(stage, '(sem stage)'),
           COALESCE(status, '(sem status)'),
           count(*),
           count(DISTINCT pedido_id),
           round(avg(duration_ms)::numeric, 2),
           max(duration_ms)
      FROM public.pedido_ingest_log
     WHERE created_at < p_ate
     GROUP BY 1, 2, 3
    ON CONFLICT (dia, stage, status) DO UPDATE
       SET total             = EXCLUDED.total,
           pedidos_distintos = EXCLUDED.pedidos_distintos,
           duracao_ms_media  = EXCLUDED.duracao_ms_media,
           duracao_ms_max    = EXCLUDED.duracao_ms_max,
           atualizado_em     = now();
    GET DIAGNOSTICS v_linhas = ROW_COUNT;
    RETURN v_linhas;
END; $$;


ALTER FUNCTION "public"."rollup_ingest_daily"("p_ate" timestamp with time zone) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rollup_task_daily"("p_ate" timestamp with time zone DEFAULT "now"()) RETURNS bigint
    LANGUAGE "plpgsql"
    AS $$
DECLARE v_linhas bigint;
BEGIN
    INSERT INTO public.task_daily_stats AS d
        (dia, task_name, task_type, status, total, duracao_ms_media, duracao_ms_max)
    SELECT created_at::date,
           COALESCE(task_name, '(sem nome)'),
           COALESCE(task_type, '(sem tipo)'),
           COALESCE(status, '(sem status)'),
           count(*),
           round(avg(EXTRACT(epoch FROM (finished_at - started_at)) * 1000)::numeric, 2),
           round(max(EXTRACT(epoch FROM (finished_at - started_at)) * 1000)::numeric, 2)
      FROM public.task_execution_logs
     WHERE created_at < p_ate
     GROUP BY 1, 2, 3, 4
    ON CONFLICT (dia, task_name, task_type, status) DO UPDATE
       SET total            = EXCLUDED.total,
           duracao_ms_media = EXCLUDED.duracao_ms_media,
           duracao_ms_max   = EXCLUDED.duracao_ms_max,
           atualizado_em    = now();
    GET DIAGNOSTICS v_linhas = ROW_COUNT;
    RETURN v_linhas;
END; $$;


ALTER FUNCTION "public"."rollup_task_daily"("p_ate" timestamp with time zone) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rollup_webhook_daily"("p_ate" timestamp with time zone DEFAULT "now"()) RETURNS bigint
    LANGUAGE "plpgsql"
    AS $$
DECLARE v_linhas bigint;
BEGIN
    INSERT INTO public.webhook_daily_stats AS d
        (dia, source, provider_topic, last_status, total, entregas)
    SELECT received_at::date,
           COALESCE(source, '(sem source)'),
           COALESCE(provider_topic, '(sem topico)'),
           COALESCE(last_status, '(sem status)'),
           count(*),
           sum(COALESCE(delivery_count, 1))
      FROM public.webhook_events
     WHERE received_at < p_ate
     GROUP BY 1, 2, 3, 4
    ON CONFLICT (dia, source, provider_topic, last_status) DO UPDATE
       SET total         = EXCLUDED.total,
           entregas      = EXCLUDED.entregas,
           atualizado_em = now();
    GET DIAGNOSTICS v_linhas = ROW_COUNT;
    RETURN v_linhas;
END; $$;


ALTER FUNCTION "public"."rollup_webhook_daily"("p_ate" timestamp with time zone) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."simular_reconciliacao_item"("p_item_id" integer, "p_quantidade" numeric DEFAULT NULL::numeric) RETURNS TABLE("nivel" integer, "caminho" "text", "produto_id" integer, "sku" "text", "tipo_produto" "text", "movimento" "text", "movimentos_gerados" integer, "quantidade" numeric, "saldo_atual" numeric, "observacao" "text")
    LANGUAGE "sql" STABLE
    AS $$
WITH RECURSIVE
raiz AS (
    SELECT i.id AS item_id, i.produto_id,
           COALESCE(p_quantidade, i.quantidade, 1)::numeric AS qtd
      FROM public.itens_demanda i WHERE i.id = p_item_id
),
arvore AS (
    SELECT 0 AS nivel, p.sku::text AS caminho, p.id AS produto_id, p.sku::text AS sku,
           COALESCE(p.tipo_produto::text, 'DESCONHECIDO') AS tipo_produto,
           r.qtd AS qtd_necessaria
      FROM raiz r JOIN public.produtos p ON p.id = r.produto_id
    UNION ALL
    SELECT a.nivel + 1, a.caminho || ' > ' || comp.sku::text, comp.id, comp.sku::text,
           COALESCE(comp.tipo_produto::text, 'DESCONHECIDO'),
           a.qtd_necessaria * f.quantidade_necessaria
      FROM arvore a
      JOIN public.ficha_tecnica f ON f.produto_pai_id = a.produto_id
      JOIN public.produtos comp   ON comp.id = f.componente_id
     WHERE a.nivel < 6 AND a.tipo_produto <> 'MATERIA_PRIMA'
),
com_saldo AS (
    SELECT a.*,
           COALESCE((SELECT sum(e.saldo_atual) FROM public.estoque_atual e
                      WHERE e.produto_id = a.produto_id), 0) AS saldo,
           EXISTS (SELECT 1 FROM public.ficha_tecnica f
                    WHERE f.produto_pai_id = a.produto_id) AS tem_bom
      FROM arvore a
)
SELECT c.nivel, c.caminho, c.produto_id, c.sku, c.tipo_produto,
       CASE
           WHEN c.tipo_produto = 'SERVICO'       THEN 'NENHUM'
           WHEN c.tipo_produto = 'MATERIA_PRIMA' THEN 'CONS_MP'
           WHEN NOT c.tem_bom                    THEN 'BLOQUEADO'
           WHEN c.nivel = 0                      THEN 'PROD_ACAB'
           ELSE 'PROD_INT + CONS_INT'
       END,
       CASE
           WHEN c.tipo_produto = 'SERVICO'
             OR (c.tipo_produto <> 'MATERIA_PRIMA' AND NOT c.tem_bom) THEN 0
           WHEN c.tipo_produto <> 'MATERIA_PRIMA' AND c.nivel > 0
            AND c.saldo < c.qtd_necessaria THEN 2
           ELSE 1
       END,
       c.qtd_necessaria, c.saldo,
       CASE
           WHEN c.tipo_produto = 'SERVICO' THEN 'Serviço não movimenta estoque'
           WHEN c.tipo_produto <> 'MATERIA_PRIMA' AND NOT c.tem_bom
               THEN 'REGRA B5: ' || c.tipo_produto || ' sem ficha técnica — reconciliação falha com erro de cadastro'
           WHEN c.tipo_produto = 'MATERIA_PRIMA' AND c.saldo < c.qtd_necessaria
               THEN 'Consome direto; saldo fica ' || (c.saldo - c.qtd_necessaria)::text || ' (negativo é esperado em MP)'
           WHEN c.saldo >= c.qtd_necessaria THEN 'Há saldo: consome do estoque, sem produção JIT'
           WHEN c.nivel = 0 THEN 'Produz JIT ' || (c.qtd_necessaria - c.saldo)::text ||
                                 ' — o acabado FICA em estoque até a saída pela coleta (ver QA-5)'
           ELSE 'Produz JIT e consome no mesmo ciclo (PROD_INT + CONS_INT); saldo volta a zero'
       END
  FROM com_saldo c
 ORDER BY c.nivel, c.sku;
$$;


ALTER FUNCTION "public"."simular_reconciliacao_item"("p_item_id" integer, "p_quantidade" numeric) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."simular_reconciliacao_item"("p_item_id" integer, "p_quantidade" numeric) IS 'Verificacao V2: cascata prevista para um item, sem gravar nada. sum(movimentos_gerados) e o total esperado em movimentacoes_estoque.';



CREATE OR REPLACE FUNCTION "public"."sincronizar_tipo_produto"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    -- Se tipo_material mudou, atualizar tipo_produto
    IF NEW.tipo_material IS DISTINCT FROM OLD.tipo_material THEN
        NEW.tipo_produto := CASE
            WHEN NEW.tipo_material = 'materia_prima' THEN 'MATERIA_PRIMA'::tipo_produto_enum
            WHEN NEW.tipo_material = 'intermediario' THEN 'INTERMEDIARIO'::tipo_produto_enum
            WHEN NEW.tipo_material = 'produto_acabado' THEN 'PRODUTO_ACABADO'::tipo_produto_enum
            WHEN NEW.tipo_material = 'servico' THEN 'SERVICO'::tipo_produto_enum
            ELSE NULL
        END;
    END IF;
    
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."sincronizar_tipo_produto"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."snapshot_estoque_item"("p_item_id" integer) RETURNS TABLE("produto_id" integer, "sku" "text", "tipo" "text", "saldo" numeric, "movimentos" bigint, "ledger" bigint)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT s.produto_id, s.sku, s.tipo_produto,
           COALESCE((SELECT sum(e.saldo_atual) FROM public.estoque_atual e
                      WHERE e.produto_id = s.produto_id), 0),
           (SELECT count(*) FROM public.movimentacoes_estoque m
             WHERE m.produto_id = s.produto_id AND m.item_demanda_id = p_item_id),
           (SELECT count(*) FROM public.demanda_estoque_processado d
             WHERE d.produto_id = s.produto_id AND d.item_id = p_item_id)
      FROM (SELECT DISTINCT produto_id, sku, tipo_produto
              FROM public.simular_reconciliacao_item(p_item_id)) s
     ORDER BY s.tipo_produto, s.sku;
$$;


ALTER FUNCTION "public"."snapshot_estoque_item"("p_item_id" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."snapshot_estoque_item"("p_item_id" integer) IS 'Verificacao V2: saldo, movimentos e ledger de cada produto do item. A coluna ledger E o criterio 2 — sao as linhas de demanda_estoque_processado.';



CREATE OR REPLACE FUNCTION "public"."standardize_table_timestamps"("target_table" "text") RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    -- Check if table exists first
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = target_table) THEN
        RAISE NOTICE 'Table % does not exist, skipping.', target_table;
        RETURN;
    END IF;

    -- Add created_at if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'created_at') THEN
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN created_at TIMESTAMPTZ DEFAULT now()', target_table);
    END IF;

    -- Add updated_at if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'updated_at') THEN
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now()', target_table);
    END IF;

    -- Sync from legacy 'atualizado_em' if it exists
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'atualizado_em') THEN
        EXECUTE format('UPDATE public.%I SET updated_at = atualizado_em WHERE updated_at IS NULL', target_table);
    ELSE
        -- Ensure 'atualizado_em' exists as a fallback to avoid trigger errors
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN atualizado_em TIMESTAMPTZ DEFAULT now()', target_table);
    END IF;
END;
$$;


ALTER FUNCTION "public"."standardize_table_timestamps"("target_table" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."sync_canonical_order_compat_fields"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  IF NEW.marketplace_module_id IS NULL AND NEW.marketplace_integration_id IS NOT NULL THEN
    SELECT lower(ii.module_id)
      INTO NEW.marketplace_module_id
      FROM public.installed_integrations ii
     WHERE ii.id = NEW.marketplace_integration_id;
  END IF;

  NEW.marketplace_module_id := lower(NULLIF(NEW.marketplace_module_id, ''));
  NEW.marketplace_order_id := COALESCE(
    NULLIF(NEW.marketplace_order_id, ''), NEW.codigo_pedido_externo
  );

  -- As copias `bling_* <-> erp_*` sairam junto com as colunas. `erp_*` e a
  -- unica familia agora.
  --
  -- Sem fallback para numero_pedido em erp_order_number: ausencia de numero do
  -- ERP e um fato, e precisa continuar visivel para a reconciliacao.
  NEW.erp_store_id := NULLIF(NEW.erp_store_id, '');
  NEW.erp_order_number := NULLIF(NEW.erp_order_number, '');

  NEW.codigo_pedido_externo := COALESCE(
    NEW.codigo_pedido_externo, NEW.marketplace_order_id
  );
  NEW.numero_pedido := COALESCE(
    NULLIF(NEW.numero_pedido, ''), NEW.erp_order_number, NEW.marketplace_order_id
  );
  NEW.origem := COALESCE(
    NULLIF(NEW.origem, ''), upper(NEW.marketplace_module_id)
  );
  NEW.informacoes_cliente := COALESCE(NEW.informacoes_cliente, '{}'::jsonb);

  IF TG_OP = 'UPDATE'
     AND OLD.marketplace_module_id IS NOT NULL
     AND OLD.marketplace_order_id IS NOT NULL
     AND (
       OLD.marketplace_module_id IS DISTINCT FROM NEW.marketplace_module_id
       OR OLD.marketplace_order_id IS DISTINCT FROM NEW.marketplace_order_id
     )
     AND COALESCE(current_setting('app.allow_order_identity_correction', true), 'false') <> 'true' THEN
    RAISE EXCEPTION
      'Canonical order identity is immutable; use correct_canonical_order_identity';
  END IF;

  IF TG_OP = 'INSERT'
     AND (NEW.marketplace_module_id IS NULL OR NEW.marketplace_order_id IS NULL) THEN
    RAISE EXCEPTION
      'Canonical order identity is required (marketplace_module_id + marketplace_order_id)';
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."sync_canonical_order_compat_fields"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."sync_marketplace_snapshot_items"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  v_source text := lower(COALESCE(NEW.identity->>'ingest_source', ''));
BEGIN
  IF v_source NOT IN ('shopee', 'mercadolivre')
     OR jsonb_typeof(NEW.items) <> 'array'
     OR jsonb_array_length(NEW.items) = 0 THEN
    RETURN NEW;
  END IF;

  DELETE FROM public.itens_pedido WHERE pedido_id = NEW.pedido_id;
  INSERT INTO public.itens_pedido (
    pedido_id, produto_id, sku_externo, descricao, quantidade,
    preco_unitario, subtotal, created_at, updated_at
  )
  SELECT
    NEW.pedido_id,
    COALESCE(
      NULLIF(item->>'produto_id', '')::integer,
      (SELECT vb.produto_id FROM public.vinculos_bling vb
       WHERE vb.codigo_bling = COALESCE(item->>'sku', item->>'sku_externo') LIMIT 1),
      (SELECT p.id FROM public.produtos p
       WHERE p.sku = COALESCE(item->>'sku', item->>'sku_externo') LIMIT 1)
    ),
    COALESCE(item->>'sku', item->>'sku_externo'),
    COALESCE(item->>'name', item->>'descricao'),
    COALESCE(NULLIF(item->>'quantity', '')::numeric, NULLIF(item->>'quantidade', '')::numeric, 1),
    COALESCE(NULLIF(item->>'unit_price', '')::numeric, NULLIF(item->>'preco_unitario', '')::numeric, NULLIF(item->>'price', '')::numeric, 0),
    COALESCE(
      NULLIF(item->>'subtotal', '')::numeric,
      COALESCE(NULLIF(item->>'quantity', '')::numeric, NULLIF(item->>'quantidade', '')::numeric, 1)
      * COALESCE(NULLIF(item->>'unit_price', '')::numeric, NULLIF(item->>'preco_unitario', '')::numeric, NULLIF(item->>'price', '')::numeric, 0)
    ),
    now(), now()
  FROM jsonb_array_elements(NEW.items) AS item;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."sync_marketplace_snapshot_items"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_item_pedido_enriquece"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
    PERFORM public.itens_pedido_enriquecer(NEW.pedido_id);
    RETURN NULL;
END;
$$;


ALTER FUNCTION "public"."tg_item_pedido_enriquece"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_pedido_classifica_modalidade"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    PERFORM public.classificar_pedido_modalidade(NEW.id);
    RETURN NULL;
END;
$$;


ALTER FUNCTION "public"."tg_pedido_classifica_modalidade"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_pedidos_sync_is_flex"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_codigo varchar(50);
BEGIN
    IF NEW.modalidade_logistica_id IS NULL THEN
        NEW.is_flex := false;
        RETURN NEW;
    END IF;

    SELECT codigo INTO v_codigo
      FROM public.modalidades_logisticas
     WHERE id = NEW.modalidade_logistica_id;

    NEW.is_flex        := (v_codigo = 'FLEX');
    NEW.is_fulfillment := (v_codigo = 'FULL');

    -- Vocabulario legado na saida: COMUM -> STANDARD, FULL -> FULFILLMENT.
    -- Impressao, alertas, consolidacao e sugestoes de lote leem essa coluna.
    NEW.modalidade_logistica := CASE v_codigo
                                  WHEN 'COMUM' THEN 'STANDARD'
                                  WHEN 'FULL'  THEN 'FULFILLMENT'
                                  WHEN 'TURBO' THEN 'FLEX'
                                  ELSE v_codigo
                                END;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_pedidos_sync_is_flex"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."tg_pedidos_sync_is_flex"() IS 'DEPRECATED por construcao. Existe apenas para os consumidores legados de is_flex sobreviverem a fase 1. Turbo e classificado como is_flex = false, o que e correto e insuficiente: por isso a fase 2 existe.';



CREATE OR REPLACE FUNCTION "public"."tg_regra_logistica_sync_modalidade"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_codigo     varchar(50);
    v_tipo       varchar(20);
    v_fechamento time;
BEGIN
    IF NEW.modalidade_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT codigo, tipo_prazo INTO v_codigo, v_tipo
      FROM public.modalidades_logisticas WHERE id = NEW.modalidade_id;

    NEW.modalidade := CASE v_codigo WHEN 'COMUM' THEN 'STANDARD' ELSE v_codigo END;

    IF v_tipo = 'RELATIVO' THEN
        IF NEW.offset_etiqueta_min IS NULL OR NEW.offset_coleta_min IS NULL THEN
            RAISE EXCEPTION 'Modalidade % e de prazo RELATIVO: informe offset de etiqueta e de coleta em minutos', v_codigo
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        -- Prazo relativo nao tem hora de parede.
        NEW.horario_corte  := NULL;
        NEW.horario_coleta := NULL;
        NEW.horario_limite := NULL;
        NEW.coleta_dia_offset := 0;
        NEW.dias_semana := ARRAY[1, 2, 3, 4, 5, 6, 7];
        RETURN NEW;
    END IF;

    IF NEW.tipo_envio = 'PONTO_COLETA' THEN
        SELECT pc.horario_fechamento INTO v_fechamento
          FROM public.pontos_coleta pc WHERE pc.id = NEW.ponto_coleta_id;

        IF NEW.horario_corte IS NULL THEN
            RAISE EXCEPTION 'Informe a hora de corte: e ela que decide quais pedidos entram neste lote'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        IF NEW.ponto_coleta_id IS NULL THEN
            RAISE EXCEPTION 'Entrega em ponto de coleta exige escolher o ponto'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        IF NEW.horario_coleta IS NULL AND v_fechamento IS NULL THEN
            RAISE EXCEPTION 'O ponto de coleta nao tem hora de fechamento cadastrada. Cadastre-a no ponto, ou informe uma hora nesta janela como excecao.'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
    ELSIF NEW.horario_corte IS NULL OR NEW.horario_coleta IS NULL THEN
        RAISE EXCEPTION 'Modalidade % e de prazo FIXO: informe hora de corte e de coleta', v_codigo
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    NEW.offset_etiqueta_min := NULL;
    NEW.offset_coleta_min   := NULL;
    -- horario_limite espelha a saida efetiva, que para ponto de coleta e o
    -- fechamento do ponto quando nao ha excecao.
    NEW.horario_limite := COALESCE(NEW.horario_limite, NEW.horario_coleta, v_fechamento);
    NEW.coleta_dia_offset := CASE
        WHEN COALESCE(NEW.horario_coleta, v_fechamento) >= NEW.horario_corte THEN 0 ELSE 1 END;

    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_regra_logistica_sync_modalidade"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_regra_sincroniza_modalidade_principal"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
    IF NEW.modalidade_id IS NOT NULL THEN
        INSERT INTO public.regra_logistica_modalidades (regra_id, modalidade_id)
        VALUES (NEW.id, NEW.modalidade_id)
        ON CONFLICT DO NOTHING;
    END IF;
    -- A modalidade antiga nao e removida: se ela foi adicionada de proposito
    -- como canal extra, apagar aqui tiraria pedidos do lote em silencio.
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_regra_sincroniza_modalidade_principal"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_snapshot_classifica_modalidade"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_module text;
    v_chave  text;
    v_rotulo text;
    v_campo  text;
BEGIN
    SELECT p.marketplace_module_id INTO v_module
      FROM public.pedidos p WHERE p.id = NEW.pedido_id;

    IF v_module IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT e.chave, e.rotulo, e.campo_origem INTO v_chave, v_rotulo, v_campo
      FROM public.extrair_metodo_envio(v_module, NEW.platform_fields) e;

    IF v_chave IS NOT NULL THEN
        UPDATE public.pedidos
           SET metodo_envio_chave  = v_chave,
               metodo_envio_rotulo = COALESCE(v_rotulo, metodo_envio_rotulo)
         WHERE id = NEW.pedido_id
           AND metodo_envio_chave IS DISTINCT FROM v_chave;

        PERFORM public.registrar_metodo_envio_observado(
            v_module::varchar, NULL, v_campo::varchar, v_chave, v_rotulo, NEW.pedido_id
        );
    END IF;

    PERFORM public.classificar_pedido_modalidade(NEW.pedido_id);
    RETURN NULL;
END;
$$;


ALTER FUNCTION "public"."tg_snapshot_classifica_modalidade"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_snapshot_enriquece_itens"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
    PERFORM public.itens_pedido_enriquecer(NEW.pedido_id);
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_snapshot_enriquece_itens"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_touch_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_touch_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."trg_demandas_pedidos_sincroniza_carimbo"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_ids integer[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT array_agg(DISTINCT pedido_id) INTO v_ids FROM novos;
    ELSE
        SELECT array_agg(DISTINCT pedido_id) INTO v_ids FROM antigos;
    END IF;

    PERFORM public.despacho_sincronizar_carimbo(v_ids);
    RETURN NULL;
END;
$$;


ALTER FUNCTION "public"."trg_demandas_pedidos_sincroniza_carimbo"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."trg_demandas_producao_sincroniza_carimbo"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_ids integer[];
BEGIN
    SELECT array_agg(DISTINCT dp.pedido_id) INTO v_ids
      FROM public.demandas_pedidos dp
      JOIN novos n ON n.id = dp.demanda_id
      JOIN antigos a ON a.id = n.id
     WHERE n.status IS DISTINCT FROM a.status;

    PERFORM public.despacho_sincronizar_carimbo(v_ids);
    RETURN NULL;
END;
$$;


ALTER FUNCTION "public"."trg_demandas_producao_sincroniza_carimbo"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."truncate_if_exists"("p_table" "text") RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = p_table
    ) THEN
        EXECUTE format('TRUNCATE TABLE public.%I RESTART IDENTITY CASCADE', p_table);
    END IF;
END;
$$;


ALTER FUNCTION "public"."truncate_if_exists"("p_table" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_alertas_demanda_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_alertas_demanda_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_consolidacoes_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_consolidacoes_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_modified_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_modified_column"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_produtos_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_produtos_updated_at_column"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_updated_at_column"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."upsert_canonical_order"("p_order" "jsonb", "p_snapshot" "jsonb" DEFAULT NULL::"jsonb", "p_refs" "jsonb" DEFAULT '[]'::"jsonb") RETURNS bigint
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  v_pedido_id BIGINT;
  v_module_id TEXT := lower(NULLIF(p_order->>'marketplace_module_id', ''));
  v_marketplace_order_id TEXT := NULLIF(p_order->>'marketplace_order_id', '');
  v_ref JSONB;
BEGIN
  IF v_module_id IS NULL OR v_marketplace_order_id IS NULL THEN
    RAISE EXCEPTION
      'Canonical order identity is required (marketplace_module_id + marketplace_order_id)';
  END IF;

  INSERT INTO public.pedidos (
    marketplace_module_id, marketplace_order_id, marketplace_integration_id,
    ingest_source, erp_integration_id, erp_store_id, erp_order_id,
    erp_order_number, situacao_pedido_id, status_original, total_pedido,
    moeda, data_venda, cliente_nome, cliente_documento, cliente_telefone,
    cliente_email, is_flex, is_fulfillment, modalidade_logistica,
    servico_logistico, data_limite_envio, data_compra_marketplace,
    data_pagamento_marketplace, data_coleta, data_envio_marketplace,
    regra_logistica_integracao_id, personalizado, canal_venda_id,
    informacoes_cliente, pedido_bling_id, pedido_shopee_id,
    pedido_mercadolivre_id, buyer_username, shipping_carrier,
    message_to_seller, updated_at
  ) VALUES (
    v_module_id,
    v_marketplace_order_id,
    NULLIF(p_order->>'marketplace_integration_id', '')::INTEGER,
    NULLIF(p_order->>'ingest_source', ''),
    NULLIF(p_order->>'erp_integration_id', '')::INTEGER,
    NULLIF(p_order->>'erp_store_id', ''),
    NULLIF(p_order->>'erp_order_id', '')::BIGINT,
    NULLIF(p_order->>'erp_order_number', ''),
    NULLIF(p_order->>'situacao_pedido_id', '')::INTEGER,
    NULLIF(p_order->>'status_original', ''),
    NULLIF(p_order->>'total_pedido', '')::NUMERIC,
    COALESCE(NULLIF(p_order->>'moeda', ''), 'BRL'),
    NULLIF(p_order->>'data_venda', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'cliente_nome', ''),
    NULLIF(p_order->>'cliente_documento', ''),
    NULLIF(p_order->>'cliente_telefone', ''),
    NULLIF(p_order->>'cliente_email', ''),
    COALESCE((p_order->>'is_flex')::BOOLEAN, false),
    COALESCE((p_order->>'is_fulfillment')::BOOLEAN, false),
    NULLIF(p_order->>'modalidade_logistica', ''),
    NULLIF(p_order->>'servico_logistico', ''),
    NULLIF(p_order->>'data_limite_envio', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_compra_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_pagamento_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_coleta', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_envio_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'regra_logistica_integracao_id', '')::BIGINT,
    COALESCE((p_order->>'personalizado')::BOOLEAN, false),
    NULLIF(p_order->>'canal_venda_id', '')::INTEGER,
    COALESCE(p_order->'customer', '{}'::jsonb),
    NULLIF(p_order->>'pedido_bling_id', '')::BIGINT,
    NULLIF(p_order->>'pedido_shopee_id', '')::BIGINT,
    NULLIF(p_order->>'pedido_mercadolivre_id', '')::INTEGER,
    NULLIF(p_order->>'buyer_username', ''),
    NULLIF(p_order->>'shipping_carrier', ''),
    NULLIF(p_order->>'message_to_seller', ''),
    now()
  )
  ON CONFLICT (marketplace_module_id, marketplace_order_id)
  DO UPDATE SET
    marketplace_integration_id = COALESCE(EXCLUDED.marketplace_integration_id, public.pedidos.marketplace_integration_id),
    ingest_source = COALESCE(EXCLUDED.ingest_source, public.pedidos.ingest_source),
    erp_integration_id = COALESCE(EXCLUDED.erp_integration_id, public.pedidos.erp_integration_id),
    erp_store_id = COALESCE(EXCLUDED.erp_store_id, public.pedidos.erp_store_id),
    erp_order_id = COALESCE(EXCLUDED.erp_order_id, public.pedidos.erp_order_id),
    erp_order_number = COALESCE(EXCLUDED.erp_order_number, public.pedidos.erp_order_number),
    situacao_pedido_id = COALESCE(EXCLUDED.situacao_pedido_id, public.pedidos.situacao_pedido_id),
    status_original = COALESCE(EXCLUDED.status_original, public.pedidos.status_original),
    total_pedido = COALESCE(EXCLUDED.total_pedido, public.pedidos.total_pedido),
    moeda = COALESCE(EXCLUDED.moeda, public.pedidos.moeda),
    data_venda = COALESCE(EXCLUDED.data_venda, public.pedidos.data_venda),
    cliente_nome = COALESCE(EXCLUDED.cliente_nome, public.pedidos.cliente_nome),
    cliente_documento = COALESCE(EXCLUDED.cliente_documento, public.pedidos.cliente_documento),
    cliente_telefone = COALESCE(EXCLUDED.cliente_telefone, public.pedidos.cliente_telefone),
    cliente_email = COALESCE(EXCLUDED.cliente_email, public.pedidos.cliente_email),
    is_flex = CASE WHEN p_order ? 'is_flex' THEN EXCLUDED.is_flex ELSE public.pedidos.is_flex END,
    is_fulfillment = CASE WHEN p_order ? 'is_fulfillment' THEN EXCLUDED.is_fulfillment ELSE public.pedidos.is_fulfillment END,
    modalidade_logistica = COALESCE(EXCLUDED.modalidade_logistica, public.pedidos.modalidade_logistica),
    servico_logistico = COALESCE(EXCLUDED.servico_logistico, public.pedidos.servico_logistico),
    data_limite_envio = COALESCE(EXCLUDED.data_limite_envio, public.pedidos.data_limite_envio),
    data_compra_marketplace = COALESCE(EXCLUDED.data_compra_marketplace, public.pedidos.data_compra_marketplace),
    data_pagamento_marketplace = COALESCE(EXCLUDED.data_pagamento_marketplace, public.pedidos.data_pagamento_marketplace),
    data_coleta = COALESCE(EXCLUDED.data_coleta, public.pedidos.data_coleta),
    data_envio_marketplace = COALESCE(EXCLUDED.data_envio_marketplace, public.pedidos.data_envio_marketplace),
    regra_logistica_integracao_id = COALESCE(EXCLUDED.regra_logistica_integracao_id, public.pedidos.regra_logistica_integracao_id),
    personalizado = CASE WHEN p_order ? 'personalizado' THEN EXCLUDED.personalizado ELSE public.pedidos.personalizado END,
    canal_venda_id = COALESCE(EXCLUDED.canal_venda_id, public.pedidos.canal_venda_id),
    informacoes_cliente = CASE
      WHEN EXCLUDED.informacoes_cliente = '{}'::jsonb THEN public.pedidos.informacoes_cliente
      ELSE EXCLUDED.informacoes_cliente
    END,
    pedido_bling_id = COALESCE(EXCLUDED.pedido_bling_id, public.pedidos.pedido_bling_id),
    pedido_shopee_id = COALESCE(EXCLUDED.pedido_shopee_id, public.pedidos.pedido_shopee_id),
    pedido_mercadolivre_id = COALESCE(EXCLUDED.pedido_mercadolivre_id, public.pedidos.pedido_mercadolivre_id),
    buyer_username = COALESCE(EXCLUDED.buyer_username, public.pedidos.buyer_username),
    shipping_carrier = COALESCE(EXCLUDED.shipping_carrier, public.pedidos.shipping_carrier),
    message_to_seller = COALESCE(EXCLUDED.message_to_seller, public.pedidos.message_to_seller),
    updated_at = now()
  RETURNING id INTO v_pedido_id;

  IF p_snapshot IS NOT NULL THEN
    INSERT INTO public.pedido_snapshots (
      pedido_id, identity, customer, items, logistics, financial,
      platform_fields, raw_refs, source_history, updated_at
    ) VALUES (
      v_pedido_id,
      COALESCE(p_snapshot->'identity', '{}'::jsonb),
      COALESCE(p_snapshot->'customer', '{}'::jsonb),
      COALESCE(p_snapshot->'items', '[]'::jsonb),
      COALESCE(p_snapshot->'logistics', '{}'::jsonb),
      COALESCE(p_snapshot->'financial', '{}'::jsonb),
      COALESCE(p_snapshot->'platform_fields', '{}'::jsonb),
      COALESCE(p_snapshot->'raw_refs', '{}'::jsonb),
      COALESCE(p_snapshot->'source_history', '[]'::jsonb),
      now()
    )
    ON CONFLICT (pedido_id) DO UPDATE SET
      identity = public.pedido_snapshots.identity || EXCLUDED.identity,
      customer = public.pedido_snapshots.customer || EXCLUDED.customer,
      items = CASE WHEN EXCLUDED.items = '[]'::jsonb
        THEN public.pedido_snapshots.items ELSE EXCLUDED.items END,
      logistics = public.pedido_snapshots.logistics || EXCLUDED.logistics,
      financial = public.pedido_snapshots.financial || EXCLUDED.financial,
      platform_fields = public.pedido_snapshots.platform_fields || EXCLUDED.platform_fields,
      raw_refs = public.pedido_snapshots.raw_refs || EXCLUDED.raw_refs,
      source_history = COALESCE(public.pedido_snapshots.source_history, '[]'::jsonb)
        || COALESCE(EXCLUDED.source_history, '[]'::jsonb),
      updated_at = now();
  END IF;

  FOR v_ref IN
    SELECT value FROM jsonb_array_elements(COALESCE(p_refs, '[]'::jsonb))
  LOOP
    IF v_ref->>'role' = 'sales_origin' THEN
      INSERT INTO public.pedido_integration_refs (
        pedido_id, integration_id, module_id, role, external_order_id,
        external_record_id, external_status, last_synced_at, metadata
      ) VALUES (
        v_pedido_id,
        NULLIF(v_ref->>'integration_id', '')::INTEGER,
        lower(v_ref->>'module_id'),
        'sales_origin',
        v_ref->>'external_order_id',
        NULLIF(v_ref->>'external_record_id', ''),
        NULLIF(v_ref->>'external_status', ''),
        COALESCE(NULLIF(v_ref->>'last_synced_at', '')::TIMESTAMPTZ, now()),
        COALESCE(v_ref->'metadata', '{}'::jsonb)
      )
      ON CONFLICT (module_id, external_order_id)
        WHERE role = 'sales_origin'
      DO UPDATE SET
        pedido_id = EXCLUDED.pedido_id,
        integration_id = COALESCE(EXCLUDED.integration_id, public.pedido_integration_refs.integration_id),
        external_record_id = COALESCE(EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id),
        external_status = COALESCE(EXCLUDED.external_status, public.pedido_integration_refs.external_status),
        last_synced_at = EXCLUDED.last_synced_at,
        metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
        updated_at = now();
    ELSE
      INSERT INTO public.pedido_integration_refs (
        pedido_id, integration_id, module_id, role, external_order_id,
        external_record_id, external_status, last_synced_at, metadata
      ) VALUES (
        v_pedido_id,
        NULLIF(v_ref->>'integration_id', '')::INTEGER,
        lower(v_ref->>'module_id'),
        v_ref->>'role',
        v_ref->>'external_order_id',
        NULLIF(v_ref->>'external_record_id', ''),
        NULLIF(v_ref->>'external_status', ''),
        COALESCE(NULLIF(v_ref->>'last_synced_at', '')::TIMESTAMPTZ, now()),
        COALESCE(v_ref->'metadata', '{}'::jsonb)
      )
      ON CONFLICT (pedido_id, integration_id, role)
      DO UPDATE SET
        module_id = EXCLUDED.module_id,
        external_order_id = EXCLUDED.external_order_id,
        external_record_id = COALESCE(EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id),
        external_status = COALESCE(EXCLUDED.external_status, public.pedido_integration_refs.external_status),
        last_synced_at = EXCLUDED.last_synced_at,
        metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
        updated_at = now();
    END IF;
  END LOOP;

  UPDATE public.pending_marketplace_enrichments
     SET status = CASE WHEN COALESCE(p_order->>'ingest_source', '') = 'bling'
                       THEN 'applied' ELSE 'matched' END,
         matched_pedido_id = v_pedido_id,
         applied_at = CASE WHEN COALESCE(p_order->>'ingest_source', '') = 'bling'
                           THEN now() ELSE applied_at END,
         updated_at = now()
   WHERE marketplace_module_id = v_module_id
     AND marketplace_order_id = v_marketplace_order_id
     AND status = 'pending';

  UPDATE public.pending_order_reconciliations
     SET pedido_id = v_pedido_id, status = 'applied', resolved_at = now(), updated_at = now()
   WHERE status = 'pending'
     AND erp_integration_id = NULLIF(p_order->>'erp_integration_id', '')::INTEGER
     AND erp_order_id = NULLIF(p_order->>'erp_order_id', '')::BIGINT;

  RETURN v_pedido_id;
END;
$$;


ALTER FUNCTION "public"."upsert_canonical_order"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validar_componente_ficha_tecnica"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  v_tipo_componente text;
  v_formato_pai     text;
BEGIN
  SELECT tipo_produto::text INTO v_tipo_componente
    FROM public.produtos WHERE id = NEW.componente_id;

  SELECT formato INTO v_formato_pai
    FROM public.produtos WHERE id = NEW.produto_pai_id;

  IF v_tipo_componente = 'PRODUTO_ACABADO' AND coalesce(v_formato_pai, '') <> 'kit' THEN
    RAISE EXCEPTION 'Produto acabado so pode ser componente de um kit (componente_id=%, pai=%)',
      NEW.componente_id, NEW.produto_pai_id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."validar_componente_ficha_tecnica"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validar_componente_kit"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE pai_formato text; componente_tipo text; componente_formato text;
BEGIN
 SELECT formato INTO pai_formato FROM public.produtos WHERE id=NEW.produto_pai_id;
 IF pai_formato='kit' THEN
  SELECT tipo_produto,formato INTO componente_tipo,componente_formato FROM public.produtos WHERE id=NEW.componente_id;
  IF componente_tipo IS DISTINCT FROM 'PRODUTO_ACABADO' THEN RAISE EXCEPTION 'Componente de kit deve ser PRODUTO_ACABADO (produto %)',NEW.componente_id; END IF;
  IF componente_formato='kit' THEN RAISE EXCEPTION 'Kit não pode conter outro kit (profundidade máxima 1)'; END IF;
 END IF;
 RETURN NEW;
END $$;


ALTER FUNCTION "public"."validar_componente_kit"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validar_preco_produto"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE minimo numeric;
BEGIN
 IF NEW.tipo IN ('padrao','promocional') THEN
  SELECT max(valor) INTO minimo FROM public.produto_precos WHERE produto_id=NEW.produto_id AND tipo='minimo' AND (integration_id IS NOT DISTINCT FROM NEW.integration_id) AND vigencia_fim IS NULL;
  IF minimo IS NOT NULL AND NEW.valor < minimo THEN RAISE EXCEPTION 'Preço % não pode ser menor que o preço mínimo %',NEW.valor,minimo; END IF;
 END IF;
 IF NEW.tipo='minimo' AND EXISTS (SELECT 1 FROM public.produto_precos p WHERE p.produto_id=NEW.produto_id AND p.tipo IN ('padrao','promocional') AND (p.integration_id IS NOT DISTINCT FROM NEW.integration_id) AND p.vigencia_fim IS NULL AND p.valor<NEW.valor) THEN RAISE EXCEPTION 'Preço mínimo não pode superar preço vigente do produto'; END IF;
 RETURN NEW;
END $$;


ALTER FUNCTION "public"."validar_preco_produto"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."validar_tipo_produto_variacao"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  v_pai_tipo_produto  public.tipo_produto_enum;
  v_pai_tipo_material text;
BEGIN
  -- So aplica para variacoes
  IF NEW.parent_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT tipo_produto, tipo_material
    INTO v_pai_tipo_produto, v_pai_tipo_material
    FROM public.produtos
   WHERE id = NEW.parent_id;

  IF v_pai_tipo_produto IS NOT NULL
     AND NEW.tipo_produto IS DISTINCT FROM v_pai_tipo_produto THEN
    NEW.tipo_produto := v_pai_tipo_produto;
  END IF;

  IF v_pai_tipo_material IS NOT NULL
     AND NEW.tipo_material IS DISTINCT FROM v_pai_tipo_material THEN
    NEW.tipo_material := v_pai_tipo_material;
  END IF;

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."validar_tipo_produto_variacao"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."validar_tipo_produto_variacao"() IS 'BEFORE INSERT/UPDATE em produtos: variacoes (parent_id NOT NULL) tem tipo_produto/tipo_material auto-corrigidos para casar com o pai.';



CREATE OR REPLACE FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" "text") RETURNS boolean
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    -- Verifica se já existe alocação com este correlation_id (não cancelada)
    RETURN EXISTS (
        SELECT 1 FROM "public"."demanda_alocacoes_estoque"
        WHERE correlation_id = p_correlation_id
        AND status != 'CANCELADA'
    );
END;
$$;


ALTER FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" character varying) RETURNS boolean
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM "public"."demanda_alocacoes_estoque"
        WHERE correlation_id = p_correlation_id
        AND status != 'CANCELADA'
    );
END;
$$;


ALTER FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" character varying) OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."agenda_recursos" (
    "id" integer NOT NULL,
    "recurso_id" integer NOT NULL,
    "data_inicio" timestamp without time zone NOT NULL,
    "data_fim" timestamp without time zone NOT NULL,
    "tipo_agendamento" character varying(50),
    "descricao" "text",
    "dados_agendamento" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."agenda_recursos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."agenda_recursos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."agenda_recursos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."agenda_recursos_id_seq" OWNED BY "public"."agenda_recursos"."id";



CREATE TABLE IF NOT EXISTS "public"."logs_execucao_ia" (
    "id" bigint NOT NULL,
    "order_sn" "text" NOT NULL,
    "executed_at" timestamp with time zone DEFAULT "now"(),
    "input_data" "jsonb",
    "chat_context" "jsonb",
    "extracted_personalization" "jsonb",
    "model_result" "jsonb",
    "status" "text",
    "error_message" "text",
    "user_feedback_id" bigint,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb"
);


ALTER TABLE "public"."logs_execucao_ia" OWNER TO "postgres";


ALTER TABLE "public"."logs_execucao_ia" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."ai_execution_logs_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."alertas_demanda" (
    "id" integer NOT NULL,
    "demanda_id" integer NOT NULL,
    "tipo_alerta" character varying(50) NOT NULL,
    "severidade" character varying(20) DEFAULT 'media'::character varying NOT NULL,
    "titulo" character varying(255) NOT NULL,
    "mensagem" "text" NOT NULL,
    "dados_impacto" "jsonb" DEFAULT '{}'::"jsonb",
    "requer_acao" boolean DEFAULT true,
    "resolvido" boolean DEFAULT false,
    "resolvido_em" timestamp with time zone,
    "resolvido_por" integer,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."alertas_demanda" OWNER TO "postgres";


COMMENT ON TABLE "public"."alertas_demanda" IS 'Alertas de problemas em demandas (pedido cancelado, estoque insuficiente, etc)';



COMMENT ON COLUMN "public"."alertas_demanda"."tipo_alerta" IS 'PEDIDO_CANCELADO, ESTOQUE_INSUFICIENTE, DEMANDA_ATRASADA';



COMMENT ON COLUMN "public"."alertas_demanda"."severidade" IS 'alta, media, baixa';



COMMENT ON COLUMN "public"."alertas_demanda"."dados_impacto" IS 'Detalhes do impacto (ex: {sku: {qtd_original, qtd_nova, diff}})';



CREATE SEQUENCE IF NOT EXISTS "public"."alertas_demanda_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."alertas_demanda_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."alertas_demanda_id_seq" OWNED BY "public"."alertas_demanda"."id";



CREATE TABLE IF NOT EXISTS "public"."archive_manifests" (
    "id" bigint NOT NULL,
    "dataset" "text" NOT NULL,
    "period_start" "date" NOT NULL,
    "period_end" "date" NOT NULL,
    "object_key" "text" NOT NULL,
    "row_count" bigint NOT NULL,
    "sha256" "text" NOT NULL,
    "schema_version" integer DEFAULT 1 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "archive_manifests_row_count_check" CHECK (("row_count" >= 0)),
    CONSTRAINT "archive_manifests_schema_version_check" CHECK (("schema_version" > 0)),
    CONSTRAINT "archive_manifests_sha256_check" CHECK (("sha256" ~ '^[0-9a-f]{64}$'::"text"))
);


ALTER TABLE "public"."archive_manifests" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."archive_manifests_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."archive_manifests_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."archive_manifests_id_seq" OWNED BY "public"."archive_manifests"."id";



CREATE TABLE IF NOT EXISTS "public"."cache_dashboard_pedidos" (
    "order_sn" "text" NOT NULL,
    "buyer_username" "text",
    "order_date" timestamp with time zone,
    "bling_number" "text",
    "items_summary" "jsonb",
    "has_chat" boolean DEFAULT false,
    "last_ai_status" "text",
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."cache_dashboard_pedidos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."canais_venda_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."canais_venda_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."canais_venda_id_seq" OWNED BY "public"."canais_venda"."id";



CREATE TABLE IF NOT EXISTS "public"."canal_modalidade_mapeamento" (
    "id" bigint NOT NULL,
    "canal_venda_id" bigint NOT NULL,
    "padrao_servico" character varying(255) NOT NULL,
    "modalidade" character varying(50) NOT NULL,
    "prioridade" integer DEFAULT 0,
    "ativo" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "canal_modalidade_mapeamento_modalidade_check" CHECK ((("modalidade")::"text" = ANY ((ARRAY['STANDARD'::character varying, 'EXPRESS'::character varying, 'FULFILLMENT'::character varying, 'RETIRADA'::character varying])::"text"[])))
);


ALTER TABLE "public"."canal_modalidade_mapeamento" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."canal_modalidade_mapeamento_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."canal_modalidade_mapeamento_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."canal_modalidade_mapeamento_id_seq" OWNED BY "public"."canal_modalidade_mapeamento"."id";



CREATE TABLE IF NOT EXISTS "public"."categoria_bom_regras" (
    "id" integer NOT NULL,
    "categoria_pai_id" integer NOT NULL,
    "nome_grupo" "text" NOT NULL,
    "categoria_componente_id" integer NOT NULL,
    "min_quantidade" numeric(10,2) DEFAULT 1,
    "max_quantidade" numeric(10,2) DEFAULT 1,
    "ordem" integer DEFAULT 0,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."categoria_bom_regras" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."categoria_bom_regras_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."categoria_bom_regras_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."categoria_bom_regras_id_seq" OWNED BY "public"."categoria_bom_regras"."id";



CREATE TABLE IF NOT EXISTS "public"."categorias" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "categoria_pai_id" integer,
    "nivel" integer DEFAULT 0,
    "caminho" "text",
    "ativo" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "comercializavel" boolean DEFAULT false,
    "componente" boolean DEFAULT false,
    "realtime_inventory" boolean DEFAULT false,
    "permite_arte" boolean DEFAULT false NOT NULL,
    "grupo_bom" "text",
    CONSTRAINT "categorias_grupo_bom_ck" CHECK ((("grupo_bom" IS NULL) OR ("grupo_bom" = ANY (ARRAY['MIOLO'::"text", 'CAPA'::"text", 'CONTRA'::"text", 'ACABAMENTO'::"text", 'EMBALAGEM'::"text", 'OUTRO'::"text"]))))
);


ALTER TABLE "public"."categorias" OWNER TO "postgres";


COMMENT ON COLUMN "public"."categorias"."comercializavel" IS 'Indica se os produtos desta categoria podem ser comercializados (associados em vendas, etc)';



COMMENT ON COLUMN "public"."categorias"."componente" IS 'Indica se os produtos desta categoria podem ser adicionados como componentes na lista de materiais de outros produtos';



COMMENT ON COLUMN "public"."categorias"."realtime_inventory" IS 'Se TRUE, o estoque dos produtos desta categoria é processado em tempo real durante as etapas de produção. Se FALSE (padrão), é processado apenas na finalização do item via explosão de BOM.';



COMMENT ON COLUMN "public"."categorias"."permite_arte" IS 'Permite associar arquivo local de arte para impressão aos produtos da categoria';



COMMENT ON COLUMN "public"."categorias"."grupo_bom" IS 'Grupo da categoria quando usada como componente de ficha técnica';



CREATE SEQUENCE IF NOT EXISTS "public"."categorias_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."categorias_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."categorias_id_seq" OWNED BY "public"."categorias"."id";



CREATE TABLE IF NOT EXISTS "public"."channel_connections" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "channel_id" integer NOT NULL,
    "integration_id" integer,
    "aggregator_store_id" character varying(255),
    "aggregator_store_name" character varying(255),
    "config" "jsonb" DEFAULT '{}'::"jsonb",
    "is_active" boolean DEFAULT true,
    "last_sync" timestamp with time zone,
    "sync_status" character varying(50) DEFAULT 'pending'::character varying,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "bling_integration_id" integer,
    "marketplace_integration_id" integer,
    "marketplace_module_id" character varying(100),
    "process_webhooks" boolean DEFAULT true NOT NULL,
    "ingest_origin_mode" "text" DEFAULT 'erp_bling'::"text" NOT NULL,
    CONSTRAINT "channel_connections_ingest_origin_mode_check" CHECK (("ingest_origin_mode" = ANY (ARRAY['erp_bling'::"text", 'marketplace_direct'::"text", 'erp_only_dummy'::"text"])))
);


ALTER TABLE "public"."channel_connections" OWNER TO "postgres";


COMMENT ON TABLE "public"."channel_connections" IS 'Vínculo explícito entre canal de venda e integração (substitui integracao_canais_config)';



COMMENT ON COLUMN "public"."channel_connections"."channel_id" IS 'Referência ao canal de venda (ex: Shopee, Amazon)';



COMMENT ON COLUMN "public"."channel_connections"."integration_id" IS 'Referência à instância de integração em installed_integrations';



COMMENT ON COLUMN "public"."channel_connections"."aggregator_store_id" IS 'Preenchido apenas quando a integração é um agregador (ex: Bling).
   Identifica qual loja dentro do agregador pertence a este canal.
   Ex: bling_loja_id = 204047801, 205218967';



COMMENT ON COLUMN "public"."channel_connections"."aggregator_store_name" IS 'Nome amigável da loja no agregador (ex: "Shopee Antiga", "Shopee Nova")';



COMMENT ON COLUMN "public"."channel_connections"."config" IS 'Configurações específicas desta conexão (mapeamento de status, filtros, etc.)';



COMMENT ON COLUMN "public"."channel_connections"."bling_integration_id" IS 'installed_integrations (module_id=bling) — conta Bling usada para API/token deste vínculo';



COMMENT ON COLUMN "public"."channel_connections"."marketplace_integration_id" IS 'installed_integrations (shopee, amazon, etc.) — instância marketplace associada a esta loja Bling';



COMMENT ON COLUMN "public"."channel_connections"."marketplace_module_id" IS 'Catalog module slug used to resolve channel/order origin without an installed marketplace integration.';



COMMENT ON COLUMN "public"."channel_connections"."process_webhooks" IS 'Quando false, webhooks do Bling para este vínculo ativo são ignorados pelo worker';



COMMENT ON COLUMN "public"."channel_connections"."ingest_origin_mode" IS 'Origem autoritativa do ingest: erp_bling, marketplace_direct ou erp_only_dummy';



CREATE TABLE IF NOT EXISTS "public"."componentes_ordem_producao" (
    "id" integer NOT NULL,
    "ordem_producao_id" integer NOT NULL,
    "componente_id" integer,
    "sku" character varying(100),
    "descricao" character varying(500),
    "quantidade_necessaria" numeric(15,4),
    "quantidade_utilizada" numeric(15,4) DEFAULT 0,
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."componentes_ordem_producao" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."componentes_ordem_producao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."componentes_ordem_producao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."componentes_ordem_producao_id_seq" OWNED BY "public"."componentes_ordem_producao"."id";



CREATE TABLE IF NOT EXISTS "public"."conferencias_arquivo" (
    "id" bigint NOT NULL,
    "arquivo_nome" "text" NOT NULL,
    "module_id" "text" NOT NULL,
    "marketplace_integration_id" integer,
    "filtro" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "total_linhas" integer DEFAULT 0 NOT NULL,
    "total_refs" integer DEFAULT 0 NOT NULL,
    "descartes" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "linhas" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "pedido_ids" integer[] DEFAULT '{}'::integer[] NOT NULL,
    "nao_encontrados" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "fora_da_torre" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "ingest_resultado" "jsonb",
    "erp_resultado" "jsonb",
    "demanda_id" integer,
    "criado_por" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."conferencias_arquivo" OWNER TO "postgres";


COMMENT ON TABLE "public"."conferencias_arquivo" IS 'Recorte auditavel de uma planilha: linhas normalizadas, filtro aplicado e pedidos resolvidos.';



ALTER TABLE "public"."conferencias_arquivo" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."conferencias_arquivo_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."configuracoes_aplicacao" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "valor" "jsonb" NOT NULL,
    "descricao" "text",
    "categoria" character varying(100),
    "protegido" boolean DEFAULT false,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "tipo_valor" character varying(50) DEFAULT 'json'::character varying,
    "entidade_tipo" character varying(50),
    "entidade_id" integer,
    "migrada_de_json" boolean DEFAULT false,
    "atualizado_em" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "chk_entidade_consistency" CHECK (((("entidade_tipo" IS NULL) AND ("entidade_id" IS NULL)) OR (("entidade_tipo" IS NOT NULL) AND ("entidade_id" IS NOT NULL)))),
    CONSTRAINT "chk_nome_not_empty" CHECK ((("nome" IS NULL) OR ("length"(TRIM(BOTH FROM "nome")) > 0)))
);


ALTER TABLE "public"."configuracoes_aplicacao" OWNER TO "postgres";


COMMENT ON COLUMN "public"."configuracoes_aplicacao"."valor" IS 'Configurações da aplicação. task_schedules gerencia o Celery Beat dinâmico.';



CREATE SEQUENCE IF NOT EXISTS "public"."configuracoes_aplicacao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."configuracoes_aplicacao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."configuracoes_aplicacao_id_seq" OWNED BY "public"."configuracoes_aplicacao"."id";



CREATE TABLE IF NOT EXISTS "public"."consolidacoes_pedido" (
    "id" bigint NOT NULL,
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying NOT NULL,
    "platform" character varying(100) NOT NULL,
    "channel_id" bigint NOT NULL,
    "channel_slug" character varying(100),
    "file_path" character varying(500),
    "file_name" character varying(255),
    "period_filter_start" timestamp with time zone,
    "period_filter_end" timestamp with time zone,
    "options" "jsonb" DEFAULT '{}'::"jsonb",
    "result_data" "jsonb",
    "error_message" "text",
    "processing_started_at" timestamp with time zone,
    "processing_completed_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."consolidacoes_pedido" OWNER TO "postgres";


COMMENT ON TABLE "public"."consolidacoes_pedido" IS 'Armazena consolidações de pedidos em processamento assíncrono';



COMMENT ON COLUMN "public"."consolidacoes_pedido"."status" IS 'Status: PENDENTE, PROCESSANDO, PRONTO, ERRO';



COMMENT ON COLUMN "public"."consolidacoes_pedido"."options" IS 'Opções de processamento: print_orders, is_flex, mode, etc.';



COMMENT ON COLUMN "public"."consolidacoes_pedido"."result_data" IS 'Dados consolidados em formato JSON (capas, miolos, pedidos, etc.)';



CREATE SEQUENCE IF NOT EXISTS "public"."consolidacoes_pedido_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."consolidacoes_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."consolidacoes_pedido_id_seq" OWNED BY "public"."consolidacoes_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."contas_bling" (
    "id" character varying NOT NULL,
    "nome" character varying(255) NOT NULL,
    "api_key" character varying(255),
    "endpoint" character varying(500),
    "ativa" boolean DEFAULT true,
    "dados_autenticacao" "jsonb",
    "ultima_verificacao" timestamp without time zone,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "cnpj" character varying,
    "client_id" character varying,
    "client_secret" character varying,
    "access_token" character varying,
    "refresh_token" character varying,
    "expires_in" integer,
    "platform_name" character varying,
    "icon_url" character varying,
    "instance_name" character varying,
    "versao_api" character varying
);


ALTER TABLE "public"."contas_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."contas_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."contas_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."contas_bling_id_seq" OWNED BY "public"."contas_bling"."id";



CREATE TABLE IF NOT EXISTS "public"."contextos_producao" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tipo" character varying(50) NOT NULL,
    "pedido_id" integer,
    "demanda_id" integer,
    "canal_venda_id" integer NOT NULL,
    "snapshot_plataforma" "jsonb" DEFAULT '{}'::"jsonb",
    "snapshot_integracao" "jsonb" DEFAULT '{}'::"jsonb",
    "snapshot_logistica" "jsonb" DEFAULT '{}'::"jsonb",
    "snapshot_temporal" "jsonb" DEFAULT '{}'::"jsonb",
    "snapshot_priorizacao" "jsonb" DEFAULT '{}'::"jsonb",
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."contextos_producao" OWNER TO "postgres";


COMMENT ON TABLE "public"."contextos_producao" IS 'Contexto unificado de produção que sintetiza relações entre plataformas, canais, integrações, logística, pedidos e demandas';



COMMENT ON COLUMN "public"."contextos_producao"."tipo" IS 'Tipo de contexto: PEDIDO_UNICO (um pedido) ou DEMANDA_CONSOLIDADA (múltiplos pedidos consolidados)';



COMMENT ON COLUMN "public"."contextos_producao"."snapshot_plataforma" IS 'Snapshot: {nome, tipo, pedido_externo_id}';



COMMENT ON COLUMN "public"."contextos_producao"."snapshot_integracao" IS 'Snapshot: {marketplace_integration_id, bling_integration_id, bling_loja_id}';



COMMENT ON COLUMN "public"."contextos_producao"."snapshot_logistica" IS 'Snapshot: {modalidade, tipo_envio, ponto_coleta_id, ponto_coleta_nome, horario_corte, is_flex, is_fulfillment}';



COMMENT ON COLUMN "public"."contextos_producao"."snapshot_temporal" IS 'Snapshot: {data_pedido, data_limite_envio, data_promessa_cliente, categoria_temporal, deadline_final}';



COMMENT ON COLUMN "public"."contextos_producao"."snapshot_priorizacao" IS 'Snapshot: {score, fatores, prioridade_manual}';



CREATE TABLE IF NOT EXISTS "public"."conversoes_uom_produto" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "unidade_origem_id" integer NOT NULL,
    "unidade_destino_id" integer NOT NULL,
    "fator_conversao" numeric(15,6),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."conversoes_uom_produto" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."conversoes_uom_produto_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."conversoes_uom_produto_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."conversoes_uom_produto_id_seq" OWNED BY "public"."conversoes_uom_produto"."id";



CREATE TABLE IF NOT EXISTS "public"."demanda_alocacoes_estoque" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "demanda_id" character varying(100) NOT NULL,
    "item_id" character varying(100) NOT NULL,
    "produto_id" character varying(100) NOT NULL,
    "correlation_id" character varying(100) NOT NULL,
    "quantidade_alocada" numeric(10,2) DEFAULT 0 NOT NULL,
    "tipo_alocacao" character varying(50) NOT NULL,
    "processo_origem" character varying(50),
    "status" character varying(20) DEFAULT 'PENDENTE'::character varying,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "processed_at" timestamp with time zone,
    "cancelled_at" timestamp with time zone,
    CONSTRAINT "chk_quantidade" CHECK (("quantidade_alocada" >= (0)::numeric)),
    CONSTRAINT "chk_status" CHECK ((("status")::"text" = ANY ((ARRAY['PENDENTE'::character varying, 'PROCESSADA'::character varying, 'CANCELADA'::character varying])::"text"[]))),
    CONSTRAINT "chk_tipo_alocacao" CHECK ((("tipo_alocacao")::"text" = ANY ((ARRAY['MANUAL_DASHBOARD'::character varying, 'FINALIZACAO'::character varying, 'PRODUCAO_JIT'::character varying, 'SAIDA_DISTRIBUIDA'::character varying, 'PREVISAO_ESTOQUE'::character varying, 'PREVISAO_PRODUCAO_JIT'::character varying])::"text"[])))
);


ALTER TABLE "public"."demanda_alocacoes_estoque" OWNER TO "postgres";


COMMENT ON TABLE "public"."demanda_alocacoes_estoque" IS 'Controle granular de alocações de estoque por demanda/item para evitar duplicação de consumo de componentes';



COMMENT ON COLUMN "public"."demanda_alocacoes_estoque"."correlation_id" IS 'ID único para rastreabilidade e idempotência - evita processamento duplicado';



COMMENT ON COLUMN "public"."demanda_alocacoes_estoque"."tipo_alocacao" IS 'Tipo de alocação: MANUAL_DASHBOARD(alocação direta pelo usuário), FINALIZACAO(processamento de BOM na finalização), PRODUCAO_JIT (produção just-in-time por etapa), SAIDA_DISTRIBUIDA (saída distribuída para múltiplas demandas)';



COMMENT ON COLUMN "public"."demanda_alocacoes_estoque"."status" IS 'PENDENTE: aguardando processamento, PROCESSADA: consumo de estoque realizado, CANCELADA: alocação cancelada/estornada';



CREATE TABLE IF NOT EXISTS "public"."demanda_estoque_processado" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "item_id" integer NOT NULL,
    "demanda_id" integer NOT NULL,
    "estagio" character varying(50) NOT NULL,
    "quantidade" numeric(10,2) NOT NULL,
    "saldo_acumulado" numeric(10,2) NOT NULL,
    "correlation_id" character varying(100),
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "tipo_movimentacao" character varying(50) DEFAULT 'CONS_MP'::character varying NOT NULL,
    "produto_id" integer,
    "usuario_id" integer,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    CONSTRAINT "check_tipo_movimentacao" CHECK ((("tipo_movimentacao")::"text" = ANY (ARRAY['CONS_MP'::"text", 'PROD_INT'::"text", 'CONS_INT'::"text", 'PROD_ACAB'::"text", 'RESERVA'::"text", 'LIB_RESERVA'::"text", 'AJUSTE'::"text", 'ESTORNO'::"text", 'SAIDA_COLETA'::"text"])))
);


ALTER TABLE "public"."demanda_estoque_processado" OWNER TO "postgres";


COMMENT ON COLUMN "public"."demanda_estoque_processado"."tipo_movimentacao" IS 'Tipo de movimentação: CONS_MP (consumo MP), PROD_INT (produção intermediária), CONS_INT (consumo intermediário), PROD_ACAB (produção acabado), RESERVA, LIB_RESERVA, AJUSTE, ESTORNO';



COMMENT ON CONSTRAINT "check_tipo_movimentacao" ON "public"."demanda_estoque_processado" IS 'SAIDA_COLETA acrescentado na QA-5: baixa do produto acabado quando a demanda e coletada por completo.';



CREATE TABLE IF NOT EXISTS "public"."demandas_item_origem" (
    "id" integer NOT NULL,
    "demanda_item_id" integer NOT NULL,
    "plataforma" character varying(50) NOT NULL,
    "pedido_externo_id" character varying(255) NOT NULL,
    "item_externo_id" character varying(255),
    "sku_externo" character varying(255) NOT NULL,
    "quantidade_atendida" integer NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "pedido_id" integer
);


ALTER TABLE "public"."demandas_item_origem" OWNER TO "postgres";


COMMENT ON COLUMN "public"."demandas_item_origem"."pedido_id" IS 'Pedido interno de origem. itens_pedido e reescrito a cada re-ingest, entao o rastro precisa apontar para o pedido, nao so para a linha de item.';



CREATE SEQUENCE IF NOT EXISTS "public"."demandas_item_origem_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."demandas_item_origem_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."demandas_item_origem_id_seq" OWNED BY "public"."demandas_item_origem"."id";



CREATE TABLE IF NOT EXISTS "public"."demandas_overrides" (
    "id" bigint NOT NULL,
    "demanda_id" bigint NOT NULL,
    "campo" character varying(50) NOT NULL,
    "valor_original" "jsonb" NOT NULL,
    "valor_alterado" "jsonb" NOT NULL,
    "justificativa" "text",
    "justificativa_tipo" character varying(50),
    "usuario_id" integer,
    "contexto_origem" character varying(50),
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."demandas_overrides" OWNER TO "postgres";


COMMENT ON TABLE "public"."demandas_overrides" IS 'Registro de personalizações de campos herdados nas demandas.
   Permite que usuários personalizem valores sugeridos (horário, modalidade, etc.)
   com rastreabilidade completa de quem alterou, quando e por quê.';



COMMENT ON COLUMN "public"."demandas_overrides"."campo" IS 'Campo personalizado: horario_coleta, modalidade_logistica, data_limite_execucao, is_flex, fulfillment';



COMMENT ON COLUMN "public"."demandas_overrides"."justificativa_tipo" IS 'COLETA_ALTERNATIVA: Plataforma definiu horário alternativo no dia
   MUDANCA_CLIENTE: Solicitação do cliente
   ERRO_OPERACIONAL: Correção de erro operacional
   OTIMIZACAO_LOGISTICA: Melhoria operacional/logística
   OUTRO: Outro motivo';



COMMENT ON COLUMN "public"."demandas_overrides"."contexto_origem" IS 'Fonte de geração da demanda: PLANILHA, MULTIPLOS_PEDIDOS, DIRETA, CONSOLIDADA';



CREATE SEQUENCE IF NOT EXISTS "public"."demandas_overrides_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."demandas_overrides_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."demandas_overrides_id_seq" OWNED BY "public"."demandas_overrides"."id";



CREATE TABLE IF NOT EXISTS "public"."demandas_pedidos" (
    "id" bigint NOT NULL,
    "demanda_id" bigint NOT NULL,
    "pedido_id" bigint NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "adicionado_apos_edicao" boolean DEFAULT false,
    "adicionado_em" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."demandas_pedidos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."demandas_pedidos_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."demandas_pedidos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."demandas_pedidos_id_seq" OWNED BY "public"."demandas_pedidos"."id";



CREATE TABLE IF NOT EXISTS "public"."demandas_producao" (
    "id" integer NOT NULL,
    "demanda_id" character varying(255) NOT NULL,
    "descricao" "text",
    "produto_id" integer,
    "quantidade" integer,
    "data_entrega" "date",
    "prioridade" integer DEFAULT 0,
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "responsavel_id" integer,
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "canal_venda_id" integer,
    "horario_coleta" time without time zone,
    "tipo_demanda" character varying(50),
    "observacoes" "text",
    "prioridade_manual" integer DEFAULT 0,
    "pedido_numero" character varying(100),
    "data_conclusao" timestamp without time zone,
    "is_flex" boolean DEFAULT false,
    "fulfillment" boolean DEFAULT false,
    "modalidade_logistica" character varying(20),
    "classificacao_cliente" character varying(10),
    "capacidade_requerida" "jsonb" DEFAULT '{}'::"jsonb",
    "categoria_demanda" "text",
    "prioridade_tipo" "text",
    "data_limite_execucao" "date",
    "data_inicio_planejada" timestamp with time zone,
    "data_fim_planejada" timestamp with time zone,
    "setores_envolvidos" "jsonb",
    "categoria_temporal" "text",
    "data_promessa_cliente" "date",
    "data_maxima_entrega" "date",
    "pedido_id" integer,
    "channel_snapshot" "jsonb" DEFAULT '{}'::"jsonb",
    "rascunho_expira_em" timestamp with time zone,
    "editado_pelo_usuario" boolean DEFAULT false,
    "editado_em" timestamp with time zone,
    "editado_por" integer,
    "pedidos_apos_edicao_qtd" integer DEFAULT 0,
    "requer_revisao" boolean DEFAULT false,
    "publicado_em" timestamp with time zone,
    "publicado_por" integer,
    "origem_demanda" character varying(20) DEFAULT 'MANUAL'::character varying,
    "data_coleta" timestamp with time zone,
    "modalidade_id" integer,
    "escopo_despacho" "jsonb",
    "demanda_origem_id" integer,
    CONSTRAINT "chk_origem_demanda" CHECK ((("origem_demanda")::"text" = ANY ((ARRAY['AUTOMATICA'::character varying, 'MANUAL'::character varying])::"text"[])))
);


ALTER TABLE "public"."demandas_producao" OWNER TO "postgres";


COMMENT ON COLUMN "public"."demandas_producao"."status" IS 'RASCUNHO = consolidacao aberta na Torre de Despacho (lote fechado, ainda nao entregue ao galpao). A interface nunca usa a palavra "rascunho" para isso: ela sugere esboco descartavel, quando e o lote sobre o qual a nota fiscal ja foi emitida.';



COMMENT ON COLUMN "public"."demandas_producao"."horario_coleta" IS 'DEPRECATED: usar channel_snapshot->>''horario_coleta''.
   Será removido na Fase 6 após validação.';



COMMENT ON COLUMN "public"."demandas_producao"."tipo_demanda" IS 'Tipo de demanda: PLATAFORMA (venda consolidada), B2B (venda corporativa), FULFILLMENT (reposição para fulfillment), ESTOQUE_INTERNO (produção para estoque interno)';



COMMENT ON COLUMN "public"."demandas_producao"."modalidade_logistica" IS 'DEPRECATED: espelho de modalidade_id durante a transicao. Nao usar como criterio de agrupamento em codigo novo.';



COMMENT ON COLUMN "public"."demandas_producao"."classificacao_cliente" IS 'Classificação do cliente: B2C (Varejo), B2B (Corporativo), INTERNO (Estoque/Amostra)';



COMMENT ON COLUMN "public"."demandas_producao"."capacidade_requerida" IS 'Capacidade requerida para a produção da demanda, segmentada por setor/turno';



COMMENT ON COLUMN "public"."demandas_producao"."pedido_id" IS 'Vínculo direto com a entidade unificada de pedidos.';



COMMENT ON COLUMN "public"."demandas_producao"."channel_snapshot" IS 'Snapshot do estado do canal no momento da criação da demanda.
   Armazena: { flex, fulfillment, horario_coleta, color, canal_nome }.
   Usado para auditoria e para garantir consistência histórica.';



COMMENT ON COLUMN "public"."demandas_producao"."rascunho_expira_em" IS 'Vestigial. Prazo de validade do rascunho automatico, aposentado em 27/08/2026. Uma consolidacao da Torre de Despacho nao expira: ela e publicada ou desfeita pelo operador. Sempre NULL em registros novos.';



COMMENT ON COLUMN "public"."demandas_producao"."origem_demanda" IS 'Origem da demanda: AUTOMATICA (webhook/forçar consolidação) ou MANUAL (criada pelo usuário)';



COMMENT ON COLUMN "public"."demandas_producao"."data_coleta" IS 'Menor data/hora de coleta dos pedidos vinculados a demanda, usada para ordenar a producao.';



COMMENT ON COLUMN "public"."demandas_producao"."escopo_despacho" IS 'Escopo reproduzivel do lancamento: {integration_id, modalidade_id, horizonte[], data_operacional, total_pedidos_no_lancamento, total_conferido_pelo_operador}.';



COMMENT ON COLUMN "public"."demandas_producao"."demanda_origem_id" IS 'Liga o lote complementar de retardatarios a demanda original do mesmo escopo. A demanda em producao nunca e alterada por pedido que chega depois.';



CREATE SEQUENCE IF NOT EXISTS "public"."demandas_producao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."demandas_producao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."demandas_producao_id_seq" OWNED BY "public"."demandas_producao"."id";



CREATE TABLE IF NOT EXISTS "public"."depositos" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "endereco" "jsonb",
    "capacidade" numeric(15,2),
    "capacidade_utilizada" numeric(15,2) DEFAULT 0,
    "tipo" character varying(50),
    "ativo" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "is_default" boolean DEFAULT false
);


ALTER TABLE "public"."depositos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."depositos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."depositos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."depositos_id_seq" OWNED BY "public"."depositos"."id";



CREATE TABLE IF NOT EXISTS "public"."metodos_envio_observados" (
    "id" integer NOT NULL,
    "module_id" character varying(100) NOT NULL,
    "integration_id" integer,
    "campo_origem" character varying(120) NOT NULL,
    "valor_bruto" "text" NOT NULL,
    "valor_normalizado" "text" NOT NULL,
    "rotulo_bruto" "text",
    "status" character varying(20) DEFAULT 'NOVO'::character varying NOT NULL,
    "modalidade_id" integer,
    "ocorrencias" integer DEFAULT 1 NOT NULL,
    "primeira_ocorrencia_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "ultima_ocorrencia_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "pedido_exemplo_id" integer,
    "alerta_emitido_em" timestamp with time zone,
    CONSTRAINT "metodos_envio_observados_status_check" CHECK ((("status")::"text" = ANY ((ARRAY['NOVO'::character varying, 'CLASSIFICADO'::character varying, 'IGNORADO'::character varying])::"text"[])))
);


ALTER TABLE "public"."metodos_envio_observados" OWNER TO "postgres";


COMMENT ON TABLE "public"."metodos_envio_observados" IS 'Todo valor distinto de metodo de envio visto no ingest. Valor nunca visto gera alerta de administracao em vez de virar STANDARD por omissao. E o gatilho de manutencao quando o marketplace lanca uma modalidade nova.';



COMMENT ON COLUMN "public"."metodos_envio_observados"."valor_bruto" IS 'Chave estavel (ex.: logistics_channel_id 90011).';



COMMENT ON COLUMN "public"."metodos_envio_observados"."rotulo_bruto" IS 'Texto de exibicao (ex.: "Entrega Turbo (SPF)"). O alerta precisa dos dois: so a chave nao permite reconhecer o que e, so o rotulo nao permite escrever regra estavel.';



CREATE TABLE IF NOT EXISTS "public"."modalidades_logisticas" (
    "id" integer NOT NULL,
    "module_id" character varying(100) NOT NULL,
    "codigo" character varying(50) NOT NULL,
    "nome" character varying(100) NOT NULL,
    "tipo_prazo" character varying(20) NOT NULL,
    "politica_lote" character varying(20) DEFAULT 'LOTE'::character varying NOT NULL,
    "nivel_interrupcao" smallint DEFAULT 0 NOT NULL,
    "corte_horario" time without time zone,
    "coleta_horario" time without time zone,
    "coleta_dia_offset" smallint DEFAULT 0 NOT NULL,
    "offset_etiqueta_min" integer,
    "offset_coleta_min" integer,
    "cor" character varying(7),
    "ordem_exibicao" smallint DEFAULT 100 NOT NULL,
    "ativo" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "entra_na_torre" boolean DEFAULT true NOT NULL,
    "entrega_rapida" boolean DEFAULT false NOT NULL,
    CONSTRAINT "modalidades_logisticas_politica_lote_check" CHECK ((("politica_lote")::"text" = ANY ((ARRAY['LOTE'::character varying, 'INDIVIDUAL'::character varying])::"text"[]))),
    CONSTRAINT "modalidades_logisticas_prazo_fixo_ck" CHECK (((("tipo_prazo")::"text" <> 'FIXO'::"text") OR ("corte_horario" IS NOT NULL))),
    CONSTRAINT "modalidades_logisticas_prazo_relativo_ck" CHECK (((("tipo_prazo")::"text" <> 'RELATIVO'::"text") OR ("offset_etiqueta_min" IS NOT NULL))),
    CONSTRAINT "modalidades_logisticas_tipo_prazo_check" CHECK ((("tipo_prazo")::"text" = ANY ((ARRAY['FIXO'::character varying, 'RELATIVO'::character varying])::"text"[])))
);


ALTER TABLE "public"."modalidades_logisticas" OWNER TO "postgres";


COMMENT ON TABLE "public"."modalidades_logisticas" IS 'Regra de despacho publicada pelo marketplace (Comum, Flex, Turbo, Full). Cadastro editavel: adicionar modalidade nao pode exigir deploy.';



COMMENT ON COLUMN "public"."modalidades_logisticas"."tipo_prazo" IS 'FIXO: deadline e um horario do dia, acumula em lote diario. RELATIVO: deadline e data_venda + offset, cada pedido tem relogio proprio.';



COMMENT ON COLUMN "public"."modalidades_logisticas"."politica_lote" IS 'INDIVIDUAL significa que uma demanda de 1 pedido e o resultado esperado, nao uma anomalia.';



COMMENT ON COLUMN "public"."modalidades_logisticas"."nivel_interrupcao" IS '0 nao interrompe a fila de producao corrente. Valores maiores furam a fila sem exigir decisao do operador.';



COMMENT ON COLUMN "public"."modalidades_logisticas"."coleta_dia_offset" IS 'Dias somados a data operacional para a coleta. Cobre corte 18:00 com coleta no dia seguinte 08:00.';



COMMENT ON COLUMN "public"."modalidades_logisticas"."offset_etiqueta_min" IS 'Somente tipo_prazo RELATIVO. Minutos apos data_venda para emissao da etiqueta. Shopee Turbo = 40.';



COMMENT ON COLUMN "public"."modalidades_logisticas"."entra_na_torre" IS 'false para modalidades despachadas pelo proprio marketplace (Full). O pedido continua classificado e visivel no detalhe; apenas nao entra no contador de conferencia da torre nem no escopo de lancamento.';



COMMENT ON COLUMN "public"."modalidades_logisticas"."entrega_rapida" IS 'Modalidade de saida curta (Shopee Flex/Turbo, ML Flex, Amazon Same Day). Exibida em banda separada na torre, acima do lote comum. Independe de tipo_prazo: Flex e FIXO e Turbo e RELATIVO, e os dois sao rapidos.';



CREATE TABLE IF NOT EXISTS "public"."regras_classificacao_modalidade" (
    "id" integer NOT NULL,
    "module_id" character varying(100) NOT NULL,
    "integration_id" integer,
    "modalidade_id" integer NOT NULL,
    "campo_origem" character varying(120) NOT NULL,
    "alvo" character varying(10) DEFAULT 'CHAVE'::character varying NOT NULL,
    "operador" character varying(20) DEFAULT 'IGUAL'::character varying NOT NULL,
    "valor" "text" NOT NULL,
    "case_sensitive" boolean DEFAULT false NOT NULL,
    "prioridade" smallint DEFAULT 100 NOT NULL,
    "ativo" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "regras_classificacao_modalidade_alvo_check" CHECK ((("alvo")::"text" = ANY (ARRAY['CHAVE'::"text", 'ROTULO'::"text", 'CANONICA'::"text"]))),
    CONSTRAINT "regras_classificacao_modalidade_operador_check" CHECK ((("operador")::"text" = ANY ((ARRAY['IGUAL'::character varying, 'CONTEM'::character varying, 'PREFIXO'::character varying, 'REGEX'::character varying])::"text"[])))
);


ALTER TABLE "public"."regras_classificacao_modalidade" OWNER TO "postgres";


COMMENT ON TABLE "public"."regras_classificacao_modalidade" IS 'Mapeia valor observado no payload da origem para modalidade. N regras para 1 modalidade e o caso normal: Shopee Turbo tem dois canais logisticos (90011 e 90012) com a mesma regra operacional.';



COMMENT ON COLUMN "public"."regras_classificacao_modalidade"."campo_origem" IS 'Caminho logico em pedido_snapshots.platform_fields, documental. Preferir identificador estavel (logistics_channel_id) a rotulo de exibicao (shipping_carrier).';



COMMENT ON COLUMN "public"."regras_classificacao_modalidade"."alvo" IS 'Contra qual coluna de pedidos a regra casa: CHAVE (metodo_envio_chave) ou ROTULO (metodo_envio_rotulo).';



COMMENT ON COLUMN "public"."regras_classificacao_modalidade"."prioridade" IS 'Menor avalia primeiro. Regras por ID estavel usam prioridade baixa; fallback por rotulo usa prioridade alta e e defensivo, nunca principal.';



CREATE OR REPLACE VIEW "public"."divergencias_regra_canal" WITH ("security_invoker"='true') AS
 SELECT "o"."module_id",
    "o"."valor_bruto" AS "canal",
    "o"."rotulo_bruto" AS "rotulo_observado",
    "o"."ocorrencias",
    "o"."modalidade_id" AS "modalidade_observada_id",
    "mo"."codigo" AS "modalidade_observada",
    "r"."id" AS "regra_id",
    "r"."modalidade_id" AS "modalidade_regra_id",
    "mr"."codigo" AS "modalidade_regra",
    "r"."prioridade"
   FROM ((("public"."metodos_envio_observados" "o"
     JOIN "public"."regras_classificacao_modalidade" "r" ON (((("r"."module_id")::"text" = ("o"."module_id")::"text") AND (("r"."alvo")::"text" = 'CHAVE'::"text") AND (("r"."operador")::"text" = 'IGUAL'::"text") AND ("lower"("r"."valor") = "lower"("o"."valor_bruto")) AND "r"."ativo")))
     LEFT JOIN "public"."modalidades_logisticas" "mo" ON (("mo"."id" = "o"."modalidade_id")))
     LEFT JOIN "public"."modalidades_logisticas" "mr" ON (("mr"."id" = "r"."modalidade_id")))
  WHERE (("o"."modalidade_id" IS NOT NULL) AND ("o"."modalidade_id" IS DISTINCT FROM "r"."modalidade_id"));


ALTER VIEW "public"."divergencias_regra_canal" OWNER TO "postgres";


COMMENT ON VIEW "public"."divergencias_regra_canal" IS 'Canais onde a regra de classificacao cadastrada discorda da modalidade ja observada no trafego. Vazia e o estado correto. Existe porque a regra do canal Shopee 90024 foi editada de Retirada para Comum em 03/08/2026 e nada acusou: 65 pedidos foram para o lote errado ate a auditoria de 26/08.';



CREATE TABLE IF NOT EXISTS "public"."entity_correlation_mapping" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "entity_type" character varying(50) NOT NULL,
    "entity_id" integer NOT NULL,
    "correlation_id" character varying(100) NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."entity_correlation_mapping" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."entrega_producao" (
    "id" "text" NOT NULL,
    "item_demanda_id" integer,
    "demanda_id" integer NOT NULL,
    "quantidade" integer NOT NULL,
    "data_entrega" "date" NOT NULL,
    "user_id" "text",
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."entrega_producao" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."erp_marketplace_links" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "erp_integration_id" integer NOT NULL,
    "marketplace_integration_id" integer,
    "erp_store_id" character varying(100) NOT NULL,
    "store_name" character varying(255),
    "config" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "marketplace_module_id" character varying(100),
    "process_webhooks" boolean DEFAULT true NOT NULL,
    "ingest_origin_mode" "text" DEFAULT 'erp_bling'::"text" NOT NULL,
    "nf_emission_mode" "text" DEFAULT 'bling'::"text" NOT NULL,
    "channel_id" integer,
    CONSTRAINT "erp_marketplace_links_ingest_origin_mode_check" CHECK (("ingest_origin_mode" = ANY (ARRAY['erp_bling'::"text", 'marketplace_direct'::"text", 'erp_only_dummy'::"text"]))),
    CONSTRAINT "erp_marketplace_links_nf_emission_mode_check" CHECK (("nf_emission_mode" = ANY (ARRAY['bling'::"text", 'local'::"text", 'disabled'::"text"])))
);


ALTER TABLE "public"."erp_marketplace_links" OWNER TO "postgres";


COMMENT ON TABLE "public"."erp_marketplace_links" IS 'Vínculo entre instância ERP (Bling) e instâncias de Marketplace. Permite que o sistema saiba qual instância de ERP Bling é associada a qual instância de integração com Marketplace.';



COMMENT ON COLUMN "public"."erp_marketplace_links"."erp_integration_id" IS 'Referência à instância de integração ERP (module_id=bling em installed_integrations)';



COMMENT ON COLUMN "public"."erp_marketplace_links"."marketplace_integration_id" IS 'Referência à instância de integração de Marketplace (shopee, amazon, etc. em installed_integrations)';



COMMENT ON COLUMN "public"."erp_marketplace_links"."erp_store_id" IS 'ID da loja dentro do ERP (ex: bling_loja_id = 204047801, 205218967)';



COMMENT ON COLUMN "public"."erp_marketplace_links"."store_name" IS 'Nome amigável da loja (ex: "Shopee Antiga", "Shopee Nova")';



COMMENT ON COLUMN "public"."erp_marketplace_links"."config" IS 'Configurações específicas deste vínculo (ex: id_campo_personalizado, mapeamentos)';



COMMENT ON COLUMN "public"."erp_marketplace_links"."marketplace_module_id" IS 'Catalog module slug for the marketplace when no installed integration exists yet.';



COMMENT ON COLUMN "public"."erp_marketplace_links"."process_webhooks" IS 'Mantem a preferencia de processamento de webhooks sincronizada com channel_connections';



COMMENT ON COLUMN "public"."erp_marketplace_links"."ingest_origin_mode" IS 'Preferencia sincronizada com channel_connections para origem autoritativa do ingest';



COMMENT ON COLUMN "public"."erp_marketplace_links"."nf_emission_mode" IS 'NF route exposed by this link: bling, local or disabled.';



COMMENT ON COLUMN "public"."erp_marketplace_links"."channel_id" IS 'Canal de venda deste vinculo. Fonte unica: substitui channel_connections.channel_id.';



CREATE TABLE IF NOT EXISTS "public"."estoque_atual" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "deposito_id" integer NOT NULL,
    "saldo_atual" numeric(15,4) DEFAULT 0,
    "nivel_minimo" numeric(15,4) DEFAULT 0,
    "nivel_maximo" numeric(15,4),
    "reservado" numeric(15,4) DEFAULT 0,
    "ultima_atualizacao" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "disponivel" numeric(15,4) GENERATED ALWAYS AS (("saldo_atual" - "reservado")) STORED
);


ALTER TABLE "public"."estoque_atual" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."estoque_atual_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."estoque_atual_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."estoque_atual_id_seq" OWNED BY "public"."estoque_atual"."id";



CREATE TABLE IF NOT EXISTS "public"."eventos_auditoria" (
    "id" integer NOT NULL,
    "tipo_evento" character varying(100) NOT NULL,
    "descricao" "text",
    "usuario_id" integer,
    "entidade_afetada" character varying(100),
    "registro_id" integer,
    "dados_anteriores" "jsonb",
    "dados_novos" "jsonb",
    "ip_origem" "inet",
    "user_agent" "text",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."eventos_auditoria" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."eventos_auditoria_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."eventos_auditoria_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."eventos_auditoria_id_seq" OWNED BY "public"."eventos_auditoria"."id";



CREATE TABLE IF NOT EXISTS "public"."eventos_pedido" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "pedido_id" integer,
    "tipo_evento" character varying(50) NOT NULL,
    "descricao" "text",
    "status_de" character varying(50),
    "status_para" character varying(50),
    "payload_origem" "jsonb",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "correlation_id" "text"
);


ALTER TABLE "public"."eventos_pedido" OWNER TO "postgres";


COMMENT ON TABLE "public"."eventos_pedido" IS 'Histórico completo de eventos e mudanças de status do pedido (Timeline).';



COMMENT ON COLUMN "public"."eventos_pedido"."correlation_id" IS 'Correlation ID for end-to-end tracing of order processing workflows';



CREATE TABLE IF NOT EXISTS "public"."eventos_producao_v2" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "item_demanda_id" integer,
    "demanda_id" integer,
    "estagio" character varying(50) NOT NULL,
    "quantidade_reportada" numeric(15,4) NOT NULL,
    "tipo_evento" character varying(20) NOT NULL,
    "processado" boolean DEFAULT false NOT NULL,
    "correlation_id" "uuid" DEFAULT "gen_random_uuid"(),
    "usuario_id" integer,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."eventos_producao_v2" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."execucoes_ai_batch" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "criado_em" timestamp with time zone DEFAULT "now"(),
    "pedido_ids" bigint[] NOT NULL,
    "total" integer NOT NULL,
    "processados" integer DEFAULT 0,
    "sucesso" integer DEFAULT 0,
    "falha" integer DEFAULT 0,
    "status" "text" DEFAULT 'PENDENTE'::"text",
    "finalizado_em" timestamp with time zone,
    "iniciado_por" "text"
);


ALTER TABLE "public"."execucoes_ai_batch" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."execucoes_ai_item" (
    "id" bigint NOT NULL,
    "batch_id" "uuid",
    "pedido_id" bigint NOT NULL,
    "status" "text" NOT NULL,
    "erro" "text",
    "duracao_ms" integer,
    "criado_em" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."execucoes_ai_item" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."execucoes_ai_item_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."execucoes_ai_item_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."execucoes_ai_item_id_seq" OWNED BY "public"."execucoes_ai_item"."id";



CREATE TABLE IF NOT EXISTS "public"."feedback_pedido" (
    "id" integer NOT NULL,
    "codigo_pedido" character varying(255) NOT NULL,
    "texto_feedback" "text",
    "avaliacao" integer,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "feedback_pedido_avaliacao_check" CHECK ((("avaliacao" >= 1) AND ("avaliacao" <= 5)))
);


ALTER TABLE "public"."feedback_pedido" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."feedback_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."feedback_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."feedback_pedido_id_seq" OWNED BY "public"."feedback_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."ficha_tecnica" (
    "id" integer NOT NULL,
    "produto_pai_id" integer,
    "componente_id" integer,
    "quantidade_necessaria" numeric(15,6) DEFAULT 1 NOT NULL,
    "unidade_medida" character varying(50) DEFAULT 'un'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "sku_produto_pai" character varying(100),
    "sku_componente" character varying(100),
    "grupo" "text"
);


ALTER TABLE "public"."ficha_tecnica" OWNER TO "postgres";


COMMENT ON COLUMN "public"."ficha_tecnica"."sku_produto_pai" IS 'SKU do produto pai para facilitar migração e estabilidade';



COMMENT ON COLUMN "public"."ficha_tecnica"."sku_componente" IS 'SKU do componente';



CREATE TABLE IF NOT EXISTS "public"."ficha_tecnica_classificacao_pendente" (
    "ficha_tecnica_id" integer NOT NULL,
    "produto_pai_id" integer,
    "componente_id" integer,
    "categoria_componente_id" integer,
    "sugestao_grupo" "text",
    "motivo" "text" NOT NULL,
    "criado_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolvido_em" timestamp with time zone
);


ALTER TABLE "public"."ficha_tecnica_classificacao_pendente" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."ficha_tecnica_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."ficha_tecnica_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."ficha_tecnica_id_seq" OWNED BY "public"."ficha_tecnica"."id";



CREATE TABLE IF NOT EXISTS "public"."fornecedor_insumos" (
    "id" integer NOT NULL,
    "fornecedor_id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "lead_time_dias" integer DEFAULT 0,
    "moq" numeric(10,2) DEFAULT 0.0,
    "unidade_compra" character varying(20),
    "preco_ultima_compra" numeric(10,4),
    "moeda" character varying(10) DEFAULT 'BRL'::character varying,
    "codigo_no_fornecedor" character varying(100),
    "link_produto_fornecedor" "text",
    "preferencial" boolean DEFAULT false,
    "created_at" timestamp without time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp without time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."fornecedor_insumos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."fornecedor_insumos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."fornecedor_insumos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."fornecedor_insumos_id_seq" OWNED BY "public"."fornecedor_insumos"."id";



CREATE TABLE IF NOT EXISTS "public"."fornecedores" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "cnpj" character varying(20),
    "contato_principal" "text",
    "informacoes_contato" "jsonb",
    "categoria" character varying(100),
    "classificacao" integer,
    "ativo" boolean DEFAULT true,
    "dados_contratuais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "fornecedores_classificacao_check" CHECK ((("classificacao" >= 1) AND ("classificacao" <= 5)))
);


ALTER TABLE "public"."fornecedores" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."fornecedores_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."fornecedores_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."fornecedores_id_seq" OWNED BY "public"."fornecedores"."id";



CREATE TABLE IF NOT EXISTS "public"."grupo_mensagens_chat_shopee" (
    "event_id" "text" NOT NULL,
    "msg_id" "text" NOT NULL
);


ALTER TABLE "public"."grupo_mensagens_chat_shopee" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ingest_daily_stats" (
    "dia" "date" NOT NULL,
    "stage" "text" DEFAULT '(sem stage)'::"text" NOT NULL,
    "status" "text" DEFAULT '(sem status)'::"text" NOT NULL,
    "total" bigint NOT NULL,
    "pedidos_distintos" bigint NOT NULL,
    "duracao_ms_media" numeric,
    "duracao_ms_max" integer,
    "atualizado_em" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."ingest_daily_stats" OWNER TO "postgres";


COMMENT ON TABLE "public"."ingest_daily_stats" IS 'Agregado diario permanente de pedido_ingest_log. Substitui o log bruto, que passa a ter retencao de 1 dia.';



CREATE SEQUENCE IF NOT EXISTS "public"."installed_integrations_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."installed_integrations_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."installed_integrations_id_seq" OWNED BY "public"."installed_integrations"."id";



CREATE TABLE IF NOT EXISTS "public"."integracao_canais_config" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "canal_venda_id" integer,
    "integration_id" integer,
    "bling_loja_id" bigint,
    "plataforma_nome" character varying(100),
    "is_active" boolean DEFAULT true,
    "is_primary" boolean DEFAULT false,
    "config_json" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "bling_integration_id" integer,
    "marketplace_integration_id" integer
);


ALTER TABLE "public"."integracao_canais_config" OWNER TO "postgres";


COMMENT ON TABLE "public"."integracao_canais_config" IS 'Configuração de vínculos entre canais de venda internos, lojas Bling e instâncias de integração';



COMMENT ON COLUMN "public"."integracao_canais_config"."canal_venda_id" IS 'Referência ao canal de venda interno (ex: Shopee, Amazon)';



COMMENT ON COLUMN "public"."integracao_canais_config"."integration_id" IS 'Deprecated: usar bling_integration_id e marketplace_integration_id';



COMMENT ON COLUMN "public"."integracao_canais_config"."bling_loja_id" IS 'ID da loja no Bling (ex: 204047801, 205218967 para Shopee)';



COMMENT ON COLUMN "public"."integracao_canais_config"."plataforma_nome" IS 'Nome da plataforma: shopee, amazon, mercadolivre, shein';



COMMENT ON COLUMN "public"."integracao_canais_config"."is_primary" IS 'Indica se este é o vínculo principal para a plataforma (útil para múltiplas lojas)';



COMMENT ON COLUMN "public"."integracao_canais_config"."config_json" IS 'Configurações adicionais específicas do vínculo';



COMMENT ON COLUMN "public"."integracao_canais_config"."bling_integration_id" IS 'installed_integrations (module_id=bling) — conta Bling usada para API/token deste vínculo';



COMMENT ON COLUMN "public"."integracao_canais_config"."marketplace_integration_id" IS 'installed_integrations (shopee, amazon, etc.) — instância marketplace associada a esta loja Bling';



CREATE TABLE IF NOT EXISTS "public"."integration_account_routing" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "module" character varying(50) DEFAULT 'bling'::character varying NOT NULL,
    "function_name" character varying(50) NOT NULL,
    "scope_type" character varying(20) NOT NULL,
    "scope_id" character varying(100),
    "account_id" character varying(255) NOT NULL,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "priority" integer DEFAULT 0
);


ALTER TABLE "public"."integration_account_routing" OWNER TO "postgres";


COMMENT ON TABLE "public"."integration_account_routing" IS 'Mapeamento granular de funções de integração para contas específicas (Multi-CNPJ).';



CREATE TABLE IF NOT EXISTS "public"."integration_app_profiles" (
    "id" bigint NOT NULL,
    "module_id" character varying(100) NOT NULL,
    "name" character varying(255) NOT NULL,
    "environment" character varying(50) DEFAULT 'production'::character varying NOT NULL,
    "redirect_uri" "text" NOT NULL,
    "auth_base_url" "text",
    "token_url" "text",
    "is_default" boolean DEFAULT false NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE "public"."integration_app_profiles" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."integration_app_profiles_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."integration_app_profiles_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."integration_app_profiles_id_seq" OWNED BY "public"."integration_app_profiles"."id";



CREATE TABLE IF NOT EXISTS "public"."integration_mapping_rules" (
    "id" bigint NOT NULL,
    "module_id" "text" NOT NULL,
    "integration_id" integer,
    "erp_marketplace_link_id" "uuid",
    "domain" "text" NOT NULL,
    "direction" "text" NOT NULL,
    "provider_value" "text" NOT NULL,
    "internal_value" "text" NOT NULL,
    "priority" integer DEFAULT 0 NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "integration_mapping_rules_check" CHECK ((("erp_marketplace_link_id" IS NULL) OR ("integration_id" IS NOT NULL))),
    CONSTRAINT "integration_mapping_rules_direction_check" CHECK (("direction" = ANY (ARRAY['inbound'::"text", 'outbound'::"text"]))),
    CONSTRAINT "integration_mapping_rules_domain_check" CHECK (("domain" = ANY (ARRAY['order_status'::"text", 'payment'::"text", 'shipping_package'::"text", 'logistics_mode'::"text", 'carrier'::"text", 'erp_warehouse'::"text", 'operation_nature'::"text", 'fiscal_series'::"text"])))
);


ALTER TABLE "public"."integration_mapping_rules" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."integration_mapping_rules_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."integration_mapping_rules_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."integration_mapping_rules_id_seq" OWNED BY "public"."integration_mapping_rules"."id";



CREATE TABLE IF NOT EXISTS "public"."integration_modules" (
    "id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "version" "text",
    "author" "text",
    "icon_url" "text",
    "category" "text",
    "tags" "text"[],
    "is_active" boolean DEFAULT true,
    "config_schema" "jsonb" DEFAULT '{}'::"jsonb",
    "auth_flow" "text",
    "auth_config" "jsonb" DEFAULT '{}'::"jsonb",
    "data_mapping_spec" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "tipo" character varying(50),
    "slug" character varying(100),
    "is_aggregator" boolean DEFAULT false
);


ALTER TABLE "public"."integration_modules" OWNER TO "postgres";


COMMENT ON TABLE "public"."integration_modules" IS 'Available integration modules for the marketplace';



COMMENT ON COLUMN "public"."integration_modules"."tipo" IS 'Tipo de plataforma: MARKETPLACE, ERP, ECOMMERCE';



COMMENT ON COLUMN "public"."integration_modules"."slug" IS 'Identificador único URL-friendly da plataforma';



COMMENT ON COLUMN "public"."integration_modules"."is_aggregator" IS 'True se a plataforma é um agregador (ex: Bling, ERPs)';



CREATE TABLE IF NOT EXISTS "public"."integration_refresh_logs" (
    "id" integer NOT NULL,
    "integration_id" integer NOT NULL,
    "status" character varying(50) NOT NULL,
    "message" "text",
    "execution_mode" character varying(50) DEFAULT 'scheduled'::character varying,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."integration_refresh_logs" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."integration_refresh_logs_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."integration_refresh_logs_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."integration_refresh_logs_id_seq" OWNED BY "public"."integration_refresh_logs"."id";



CREATE TABLE IF NOT EXISTS "public"."integration_secret_values" (
    "id" bigint NOT NULL,
    "owner_type" character varying(50) NOT NULL,
    "owner_id" character varying(255) NOT NULL,
    "secret_kind" character varying(100) NOT NULL,
    "encrypted_value" "text" NOT NULL,
    "nonce" "text" NOT NULL,
    "key_version" character varying(20) DEFAULT 'V1'::character varying NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "rotated_at" timestamp with time zone
);


ALTER TABLE "public"."integration_secret_values" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."integration_secret_values_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."integration_secret_values_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."integration_secret_values_id_seq" OWNED BY "public"."integration_secret_values"."id";



CREATE TABLE IF NOT EXISTS "public"."integration_status_mappings" (
    "id" bigint NOT NULL,
    "module_id" "text" NOT NULL,
    "integration_id" integer,
    "external_status_id" "text" NOT NULL,
    "external_status_name" "text",
    "internal_situacao_pedido_id" integer,
    "triggers_demand_consolidation" boolean DEFAULT false NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "config" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "status_domain" "text" DEFAULT 'order'::"text" NOT NULL,
    "lifecycle_stage" "text",
    "stage_rank" integer,
    "projects_situacao" boolean DEFAULT true NOT NULL,
    "is_terminal" boolean DEFAULT false NOT NULL,
    "is_modifier" boolean DEFAULT false NOT NULL,
    "implies" "text",
    CONSTRAINT "integration_status_mappings_external_situacao_check" CHECK (("internal_situacao_pedido_id" IS DISTINCT FROM 3)),
    CONSTRAINT "integration_status_mappings_lifecycle_stage_check" CHECK ((("lifecycle_stage" IS NULL) OR ("lifecycle_stage" = ANY (ARRAY['returned'::"text", 'partially_refunded'::"text", 'return_in_progress'::"text", 'delivered'::"text", 'shipped'::"text", 'shipping_exception'::"text", 'cancelled'::"text", 'cancellation_pending'::"text", 'fulfillment_ready'::"text", 'paid_preparation'::"text", 'chargeback_pending'::"text", 'payment_in_analysis'::"text", 'awaiting_payment'::"text", 'ignored'::"text", 'unknown'::"text"]))))
);


ALTER TABLE "public"."integration_status_mappings" OWNER TO "postgres";


COMMENT ON COLUMN "public"."integration_status_mappings"."status_domain" IS 'Dominio do status externo: order, payment, shipping ou package';



COMMENT ON COLUMN "public"."integration_status_mappings"."lifecycle_stage" IS 'Estagio canonico (vocabulario fechado da secao 3 da spec de canonizacao).';



COMMENT ON COLUMN "public"."integration_status_mappings"."stage_rank" IS 'Precedencia: entre observacoes do mesmo pedido vence o maior rank.';



COMMENT ON COLUMN "public"."integration_status_mappings"."is_modifier" IS 'Estagio que qualifica o estado subjacente em vez de descrever situacao propria. A decisao cai para o proximo estagio que projeta.';



COMMENT ON COLUMN "public"."integration_status_mappings"."implies" IS 'O que o valor tambem afirma sobre outros dominios. Documental, nunca a decisao.';



CREATE SEQUENCE IF NOT EXISTS "public"."integration_status_mappings_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."integration_status_mappings_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."integration_status_mappings_id_seq" OWNED BY "public"."integration_status_mappings"."id";



CREATE TABLE IF NOT EXISTS "public"."itens_demanda" (
    "id" integer NOT NULL,
    "demanda_id" integer NOT NULL,
    "produto_id" integer,
    "sku" character varying(100),
    "descricao" character varying(500),
    "quantidade" numeric(15,4),
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "capas_impressas_qtd" numeric(15,4) DEFAULT 0,
    "capas_produzidas_qtd" numeric(15,4) DEFAULT 0,
    "capas_prontas_retirada_qtd" numeric(15,4) DEFAULT 0,
    "miolos_prontos_retirada_qtd" numeric(15,4) DEFAULT 0,
    "expedicao_capas_retiradas_qtd" numeric(15,4) DEFAULT 0,
    "expedicao_miolos_retirados_qtd" numeric(15,4) DEFAULT 0,
    "status_item" character varying(50) DEFAULT 'Pendente'::character varying,
    "miolo_nome" character varying(255),
    "variacao" character varying(255),
    "id_produto_miolo" integer,
    "finalizados_qtd" numeric(15,4) DEFAULT 0,
    "status_processamento" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "quantidade_planejada" numeric(15,4),
    "sku_externo" character varying(255),
    "ordem" integer,
    "miolo_chave" "text",
    "miolo_origem" "text",
    "contabiliza_estoque" boolean DEFAULT false NOT NULL
);


ALTER TABLE "public"."itens_demanda" OWNER TO "postgres";


COMMENT ON COLUMN "public"."itens_demanda"."quantidade_planejada" IS 'Quantidade planejada para produção (diferente de quantidade que é a quantidade realizada/concluída)';



COMMENT ON COLUMN "public"."itens_demanda"."sku_externo" IS 'SKU externo (por exemplo, do Bling, Shopee, etc.) para mapeamento com sistemas externos';



COMMENT ON COLUMN "public"."itens_demanda"."ordem" IS 'Posicao na ordem de producao: miolo por carga decrescente, e dentro do miolo por quantidade decrescente. E a ordem que o galpao usa para montar o lote.';



COMMENT ON COLUMN "public"."itens_demanda"."miolo_chave" IS 'Miolo derivado do codigo do SKU. E a chave estavel de agrupamento e ordenacao; miolo_nome pode ser o nome vindo da BOM, que e so rotulo.';



COMMENT ON COLUMN "public"."itens_demanda"."miolo_origem" IS 'BOM quando o miolo veio da ficha tecnica do produto interno, SKU quando foi derivado do codigo. SKU e o caso normal e nao e uma pendencia.';



COMMENT ON COLUMN "public"."itens_demanda"."contabiliza_estoque" IS 'True somente quando a linha resolveu um produto interno. False produz igual, apenas nao movimenta estoque.';



CREATE SEQUENCE IF NOT EXISTS "public"."itens_demanda_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_demanda_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_demanda_id_seq" OWNED BY "public"."itens_demanda"."id";



CREATE TABLE IF NOT EXISTS "public"."itens_ordem_compra" (
    "id" integer NOT NULL,
    "ordem_compra_id" integer NOT NULL,
    "produto_id" integer,
    "sku" character varying(100),
    "descricao" character varying(500),
    "quantidade" integer,
    "preco_unitario" numeric(10,2),
    "subtotal" numeric(10,2),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."itens_ordem_compra" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."itens_ordem_compra_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_ordem_compra_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_ordem_compra_id_seq" OWNED BY "public"."itens_ordem_compra"."id";



CREATE TABLE IF NOT EXISTS "public"."itens_pedido_bling" (
    "id" integer NOT NULL,
    "pedido_bling_id" integer,
    "sku" character varying(255),
    "descricao" character varying(500),
    "quantidade" integer,
    "preco_unitario" numeric(10,2),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "codigo" character varying(100),
    "unidade" character varying(20),
    "valor" numeric(10,2),
    "personalizado" boolean DEFAULT false,
    "produto" "jsonb",
    "criado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "bling_item_id" bigint,
    "atualizado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."itens_pedido_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."itens_pedido_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_pedido_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_pedido_bling_id_seq" OWNED BY "public"."itens_pedido_bling"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."itens_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_pedido_id_seq" OWNED BY "public"."itens_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."janelas_despacho_execucoes" (
    "id" bigint NOT NULL,
    "integration_id" integer NOT NULL,
    "modalidade_id" integer NOT NULL,
    "tipo" character varying(10) NOT NULL,
    "janela_em" timestamp with time zone NOT NULL,
    "executado_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "demanda_id" integer,
    "qtd_pedidos" integer DEFAULT 0 NOT NULL,
    "observacao" "text",
    CONSTRAINT "janelas_despacho_execucoes_tipo_check" CHECK ((("tipo")::"text" = ANY ((ARRAY['CORTE'::character varying, 'COLETA'::character varying])::"text"[])))
);


ALTER TABLE "public"."janelas_despacho_execucoes" OWNER TO "postgres";


COMMENT ON TABLE "public"."janelas_despacho_execucoes" IS 'Janelas de corte e coleta ja processadas. Existe para idempotencia e para o catch-up de janela perdida: sem ela, um beat reiniciado refaria lotes ou pularia lotes em silencio.';



CREATE SEQUENCE IF NOT EXISTS "public"."janelas_despacho_execucoes_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."janelas_despacho_execucoes_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."janelas_despacho_execucoes_id_seq" OWNED BY "public"."janelas_despacho_execucoes"."id";



CREATE TABLE IF NOT EXISTS "public"."logs_producao_diaria" (
    "id" integer NOT NULL,
    "data" "date",
    "turno" character varying(50),
    "equipe_id" integer,
    "resumo_diario" "jsonb",
    "detalhes_producao" "jsonb",
    "problemas" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "data_registro" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "produto_id" integer,
    "produto_nome" character varying(255),
    "quantidade_produzida" numeric(15,4) DEFAULT 0,
    "ordem_producao_id" integer,
    "snapshot_estoque_componentes" "jsonb" DEFAULT '[]'::"jsonb",
    "user_email" character varying(255),
    "deleted" boolean DEFAULT false,
    "deleted_at" timestamp without time zone,
    "deleted_by" character varying(255),
    "item_demanda_id" integer,
    "demanda_nome" character varying(255)
);


ALTER TABLE "public"."logs_producao_diaria" OWNER TO "postgres";


COMMENT ON COLUMN "public"."logs_producao_diaria"."item_demanda_id" IS 'ID do item de demanda associado (opcional - NULL para produção avulsa)';



COMMENT ON COLUMN "public"."logs_producao_diaria"."demanda_nome" IS 'Nome da demanda para rastreamento em logs (opcional - NULL para produção avulsa)';



CREATE SEQUENCE IF NOT EXISTS "public"."logs_producao_diaria_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."logs_producao_diaria_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."logs_producao_diaria_id_seq" OWNED BY "public"."logs_producao_diaria"."id";



CREATE TABLE IF NOT EXISTS "public"."manutencao_status_log" (
    "id" bigint NOT NULL,
    "operacao" character varying(60) NOT NULL,
    "lote" "uuid" NOT NULL,
    "pedido_id" integer NOT NULL,
    "situacao_anterior_id" integer,
    "situacao_nova_id" integer,
    "despachado_em_anterior" timestamp with time zone,
    "executado_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "executado_por" "text"
);


ALTER TABLE "public"."manutencao_status_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."manutencao_status_log" IS 'Estado anterior de pedidos alterados por ferramentas de manutencao em massa. Existe para que um corte historico possa ser desfeito: sem isso, sobrescrever Cancelado/Devolvido como Entregue seria irreversivel.';



CREATE SEQUENCE IF NOT EXISTS "public"."manutencao_status_log_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."manutencao_status_log_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."manutencao_status_log_id_seq" OWNED BY "public"."manutencao_status_log"."id";



CREATE TABLE IF NOT EXISTS "public"."marketplace_order_effects" (
    "id" bigint NOT NULL,
    "pedido_id" bigint NOT NULL,
    "transition_id" bigint NOT NULL,
    "effect_type" "text" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "attempt_count" integer DEFAULT 0 NOT NULL,
    "last_error" "text",
    "processed_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."marketplace_order_effects" OWNER TO "postgres";


ALTER TABLE "public"."marketplace_order_effects" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."marketplace_order_effects_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."marketplace_order_transitions" (
    "id" bigint NOT NULL,
    "pedido_id" bigint NOT NULL,
    "webhook_event_id" bigint,
    "provider_event_id" "text",
    "module_id" "text" NOT NULL,
    "external_order_id" "text" NOT NULL,
    "lifecycle_stage" "text" NOT NULL,
    "previous_situacao_pedido_id" integer,
    "requested_situacao_pedido_id" integer,
    "applied_situacao_pedido_id" integer,
    "decision" "text" NOT NULL,
    "reason" "text",
    "provider_updated_at" timestamp with time zone,
    "provider_state" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."marketplace_order_transitions" OWNER TO "postgres";


ALTER TABLE "public"."marketplace_order_transitions" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."marketplace_order_transitions_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."mensagem_chat_shopee" (
    "id" "text" NOT NULL,
    "shop_id" bigint,
    "request_id" "text",
    "from_id" bigint,
    "to_id" bigint,
    "from_shop_id" bigint,
    "to_shop_id" bigint,
    "from_user_name" "text",
    "to_user_name" "text",
    "type" "text",
    "conversation_id" bigint,
    "faq_session_id" bigint,
    "source_type" "text",
    "created_timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone,
    "status" "text",
    "message_option" integer,
    "source" "text",
    "content" "jsonb",
    "faq_info" "jsonb",
    "source_content" "jsonb",
    "raw_json" "jsonb",
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "installed_integration_id" bigint,
    "provider_message_id" "text",
    "webhook_event_id" bigint,
    "ingestion_source" "text" DEFAULT 'legacy'::"text" NOT NULL,
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "raw_payload" "jsonb",
    "business_type" smallint DEFAULT 0 NOT NULL,
    "region" "text",
    "is_in_chatbot_session" boolean,
    "quoted_msg" "jsonb",
    "sub_account_id" bigint,
    "sub_account_name" "text",
    "shopee_chatbot_replied" boolean,
    "raw_archived_at" timestamp with time zone,
    "archive_object_key" "text"
);


ALTER TABLE "public"."mensagem_chat_shopee" OWNER TO "postgres";


COMMENT ON COLUMN "public"."mensagem_chat_shopee"."provider_message_id" IS 'ID imutavel da mensagem no SellerChat; usado para idempotencia.';



COMMENT ON COLUMN "public"."mensagem_chat_shopee"."raw_payload" IS 'Payload bruto recebido ou retornado pela API SellerChat para auditoria.';



CREATE SEQUENCE IF NOT EXISTS "public"."metodos_envio_observados_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."metodos_envio_observados_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."metodos_envio_observados_id_seq" OWNED BY "public"."metodos_envio_observados"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."modalidades_logisticas_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."modalidades_logisticas_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."modalidades_logisticas_id_seq" OWNED BY "public"."modalidades_logisticas"."id";



CREATE TABLE IF NOT EXISTS "public"."movimentacoes_estoque" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "deposito_id" integer NOT NULL,
    "tipo_movimentacao" character varying(50) NOT NULL,
    "quantidade" numeric(15,4) NOT NULL,
    "saldo_antes" numeric(15,4),
    "saldo_depois" numeric(15,4),
    "documento_referencia" character varying(255),
    "motivo" "text",
    "usuario_id" integer,
    "data_movimentacao" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "observacao" "text",
    "correlation_id" "uuid" DEFAULT "gen_random_uuid"(),
    "origem_tipo" integer,
    "produto_nome" character varying(255),
    "demanda_nome" character varying(255),
    "idempotency_key" "text",
    "is_jit" boolean DEFAULT false,
    "coluna_origem" character varying(50),
    "lote_id" "uuid",
    "parent_movimento_id" integer,
    "item_demanda_id" integer,
    "estagio" character varying(50)
);


ALTER TABLE "public"."movimentacoes_estoque" OWNER TO "postgres";


COMMENT ON COLUMN "public"."movimentacoes_estoque"."produto_nome" IS 'Nome do produto para rastreamento em logs (pode ser NULL para produção avulsa)';



COMMENT ON COLUMN "public"."movimentacoes_estoque"."demanda_nome" IS 'Nome da demanda para rastreamento em logs (pode ser NULL para produção avulsa)';



COMMENT ON COLUMN "public"."movimentacoes_estoque"."is_jit" IS 'Indica se a movimentação é de produção JIT (compensatória)';



COMMENT ON COLUMN "public"."movimentacoes_estoque"."coluna_origem" IS 'Coluna do dashboard que originou a movimentação (E1-E7, etc)';



COMMENT ON COLUMN "public"."movimentacoes_estoque"."lote_id" IS 'ID do lote para garantir idempotência do processamento';



COMMENT ON COLUMN "public"."movimentacoes_estoque"."parent_movimento_id" IS 'Link entre produção JIT e seus consumos de componentes associados';



COMMENT ON COLUMN "public"."movimentacoes_estoque"."item_demanda_id" IS 'Link direto com o item de demanda para reconciliação incremental';



COMMENT ON COLUMN "public"."movimentacoes_estoque"."estagio" IS 'Estagio da reconciliacao que originou o movimento (ex: finalizados_qtd, bom_137). Usado pelo agrupamento da view view_movimentacoes_consolidadas para distinguir sub-arvores BOM dentro do mesmo correlation_id.';



CREATE SEQUENCE IF NOT EXISTS "public"."movimentacoes_estoque_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."movimentacoes_estoque_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."movimentacoes_estoque_id_seq" OWNED BY "public"."movimentacoes_estoque"."id";



CREATE TABLE IF NOT EXISTS "public"."notificacoes" (
    "id" integer NOT NULL,
    "titulo" character varying(255) NOT NULL,
    "mensagem" "text" NOT NULL,
    "tipo" character varying(50),
    "nivel_critica" character varying(20) DEFAULT 'MEDIA'::character varying,
    "destinatarios" "jsonb",
    "lida" boolean DEFAULT false,
    "data_envio" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "data_visualizacao" timestamp without time zone,
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."notificacoes" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."notificacoes_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."notificacoes_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."notificacoes_id_seq" OWNED BY "public"."notificacoes"."id";



CREATE TABLE IF NOT EXISTS "public"."oauth_authorization_sessions" (
    "id" bigint NOT NULL,
    "state_hash" character varying(128) NOT NULL,
    "module_id" character varying(100) NOT NULL,
    "app_profile_id" bigint,
    "installed_integration_id" integer NOT NULL,
    "redirect_uri" "text" NOT NULL,
    "code_verifier_encrypted" "text",
    "return_to" "text",
    "expires_at" timestamp with time zone NOT NULL,
    "consumed_at" timestamp with time zone,
    "status" character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    "error" "text",
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE "public"."oauth_authorization_sessions" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."oauth_authorization_sessions_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."oauth_authorization_sessions_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."oauth_authorization_sessions_id_seq" OWNED BY "public"."oauth_authorization_sessions"."id";



CREATE TABLE IF NOT EXISTS "public"."ordens_compra" (
    "id" integer NOT NULL,
    "ordem_compra_id" character varying(255) NOT NULL,
    "numero_ordem" character varying(100),
    "fornecedor_id" integer,
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "data_emissao" "date",
    "data_entrega_prevista" "date",
    "valor_total" numeric(10,2),
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."ordens_compra" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."ordens_compra_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."ordens_compra_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."ordens_compra_id_seq" OWNED BY "public"."ordens_compra"."id";



CREATE TABLE IF NOT EXISTS "public"."ordens_producao" (
    "id" integer NOT NULL,
    "ordem_id" character varying(255) NOT NULL,
    "numero_ordem" character varying(100),
    "produto_id" integer,
    "sku" character varying(100),
    "descricao" "text",
    "quantidade" numeric(15,4),
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "data_inicio" "date",
    "data_fim" "date",
    "prioridade" integer DEFAULT 0,
    "responsavel_id" integer,
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "quantidade_produzida" numeric(15,4) DEFAULT 0,
    "data_finalizacao_prevista" timestamp without time zone
);


ALTER TABLE "public"."ordens_producao" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."ordens_producao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."ordens_producao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."ordens_producao_id_seq" OWNED BY "public"."ordens_producao"."id";



CREATE TABLE IF NOT EXISTS "public"."order_identity_corrections" (
    "id" bigint NOT NULL,
    "pedido_id" bigint NOT NULL,
    "old_marketplace_module_id" "text" NOT NULL,
    "old_marketplace_order_id" "text" NOT NULL,
    "new_marketplace_module_id" "text" NOT NULL,
    "new_marketplace_order_id" "text" NOT NULL,
    "reason" "text" NOT NULL,
    "actor_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."order_identity_corrections" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."order_identity_corrections_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."order_identity_corrections_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."order_identity_corrections_id_seq" OWNED BY "public"."order_identity_corrections"."id";



CREATE TABLE IF NOT EXISTS "public"."pedido_ingest_log" (
    "id" bigint NOT NULL,
    "pedido_id" bigint,
    "bling_id" bigint,
    "marketplace_integration_id" integer,
    "is_flex" boolean,
    "flex_motivo" "text",
    "matched_rule_id" integer,
    "raw_decision" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "correlation_id" "uuid",
    "bling_integration_id" integer,
    "numero_loja" "text",
    "stage" "text",
    "status" "text",
    "message" "text",
    "duration_ms" integer,
    "payload_summary" "jsonb"
);


ALTER TABLE "public"."pedido_ingest_log" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedido_ingest_log_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedido_ingest_log_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedido_ingest_log_id_seq" OWNED BY "public"."pedido_ingest_log"."id";



CREATE TABLE IF NOT EXISTS "public"."pedido_integration_refs" (
    "id" bigint NOT NULL,
    "pedido_id" bigint NOT NULL,
    "integration_id" integer,
    "module_id" "text" NOT NULL,
    "role" "text" NOT NULL,
    "external_order_id" "text" NOT NULL,
    "external_record_id" "text",
    "external_status" "text",
    "last_synced_at" timestamp with time zone,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "pedido_integration_refs_role_check" CHECK (("role" = ANY (ARRAY['sales_origin'::"text", 'ingest_source'::"text", 'erp'::"text", 'enrichment'::"text"])))
);


ALTER TABLE "public"."pedido_integration_refs" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedido_integration_refs_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedido_integration_refs_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedido_integration_refs_id_seq" OWNED BY "public"."pedido_integration_refs"."id";



CREATE TABLE IF NOT EXISTS "public"."pedido_snapshots" (
    "id" bigint NOT NULL,
    "pedido_id" integer NOT NULL,
    "identity" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "customer" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "items" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "logistics" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "financial" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "platform_fields" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "raw_refs" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "source_history" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."pedido_snapshots" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedido_snapshots_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedido_snapshots_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedido_snapshots_id_seq" OWNED BY "public"."pedido_snapshots"."id";



CREATE TABLE IF NOT EXISTS "public"."pedidos_bling" (
    "id" integer NOT NULL,
    "numero_pedido" character varying(255) NOT NULL,
    "loja_id" integer,
    "situacao_pedido" character varying(100),
    "data_pedido" "date",
    "valor_total" numeric(10,2),
    "nome_cliente" character varying(255),
    "email_cliente" character varying(255),
    "telefone_cliente" character varying(50),
    "endereco_entrega" "jsonb",
    "itens" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "contato" "text",
    "personalizado" boolean DEFAULT false,
    "bling_id" bigint,
    "deletado" boolean DEFAULT false,
    "criado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "atualizado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "numero_loja" "text",
    "situacao_id" integer,
    "situacao_valor" integer,
    "transporte" "jsonb",
    "intermediador_cnpj" "text",
    "observacoes" "text",
    "observacoes_internas" "text",
    "raw_payload" "jsonb",
    "integracao_instancia_id" bigint,
    "bling_integration_id" integer
);


ALTER TABLE "public"."pedidos_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_bling_id_seq" OWNED BY "public"."pedidos_bling"."id";



CREATE OR REPLACE VIEW "public"."pedidos_com_external_id" AS
 SELECT "id",
    "uuid_pedido",
    "numero_pedido",
    "codigo_pedido_externo",
    "origem",
    "informacoes_cliente",
    "situacao_pedido_id",
    "total_pedido",
    "moeda",
    "data_venda",
    "created_at",
    "updated_at",
    "cliente_nome",
    "cliente_documento",
    "canal_venda_id",
    "cliente_telefone",
    "cliente_email",
    "is_flex",
    "data_limite_envio",
    "servico_logistico",
    "payload_canonico",
    "channel_snapshot",
    COALESCE("codigo_pedido_externo", "public"."fn_external_id"("id", "origem")) AS "external_id"
   FROM "public"."pedidos" "p";


ALTER VIEW "public"."pedidos_com_external_id" OWNER TO "postgres";


COMMENT ON VIEW "public"."pedidos_com_external_id" IS 'View de compatibilidade que retorna pedidos com external_id resolvido.
   Prioriza codigo_pedido_externo (legado), fallback para fn_external_id().
   Será removida na Fase 6.';



CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_id_seq" OWNED BY "public"."pedidos"."id";



CREATE TABLE IF NOT EXISTS "public"."pedidos_mercadolivre" (
    "id" integer NOT NULL,
    "codigo_pedido" character varying(255) NOT NULL,
    "shipment_id" bigint,
    "status" character varying(100),
    "mode" character varying(50),
    "shipping_type" character varying(50),
    "shipping_option_name" character varying(100),
    "expected_date" timestamp with time zone,
    "buyer_nickname" character varying(255),
    "raw_order" "jsonb",
    "raw_shipment" "jsonb",
    "raw_sla" "jsonb",
    "marketplace_integration_id" integer,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "date_approved" timestamp with time zone
);


ALTER TABLE "public"."pedidos_mercadolivre" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_mercadolivre_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_mercadolivre_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_mercadolivre_id_seq" OWNED BY "public"."pedidos_mercadolivre"."id";



CREATE TABLE IF NOT EXISTS "public"."pedidos_nao_classificados" (
    "id" bigint NOT NULL,
    "pedido_id" bigint NOT NULL,
    "canal_venda_id" bigint NOT NULL,
    "servico_logistico_recebido" character varying(500) NOT NULL,
    "tentativas_classificacao" integer DEFAULT 1,
    "resolvido" boolean DEFAULT false,
    "resolvido_em" timestamp with time zone,
    "resolvido_por" integer,
    "modalidade_atribuida" character varying(50),
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."pedidos_nao_classificados" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_nao_classificados_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_nao_classificados_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_nao_classificados_id_seq" OWNED BY "public"."pedidos_nao_classificados"."id";



CREATE TABLE IF NOT EXISTS "public"."pedidos_shopee" (
    "id" integer NOT NULL,
    "codigo_pedido" character varying(255) NOT NULL,
    "id_pedido_shopee" bigint,
    "status_pedido" character varying(100),
    "valor_total" numeric(10,2),
    "moeda" character varying(10),
    "data_criacao" timestamp without time zone,
    "data_atualizacao" timestamp without time zone,
    "data_pagamento" timestamp without time zone,
    "dias_para_envio" integer,
    "data_envio" timestamp without time zone,
    "endereco_entrega" "jsonb",
    "itens_pedido" "jsonb",
    "informacoes_comprador" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "mensagem" "text",
    "shipping_carrier" character varying(255),
    "fulfillment_flag" "text",
    "package_list" "jsonb",
    "pay_time" timestamp with time zone,
    "recipient_address" "jsonb",
    "item_list" "jsonb",
    "shop_id" bigint,
    "raw_payload" "jsonb",
    "enriched_at" timestamp with time zone,
    "order_sn" "text",
    "order_status" "text",
    "buyer_username" "text",
    "buyer_user_id" bigint,
    "marketplace_integration_id" integer
);


ALTER TABLE "public"."pedidos_shopee" OWNER TO "postgres";


COMMENT ON COLUMN "public"."pedidos_shopee"."shipping_carrier" IS 'Shipping carrier from Shopee API. Used for FLEX classification (Entrega Rápida detection)';



CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_shopee_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_shopee_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_shopee_id_seq" OWNED BY "public"."pedidos_shopee"."id";



CREATE TABLE IF NOT EXISTS "public"."pending_marketplace_enrichments" (
    "id" bigint NOT NULL,
    "marketplace_integration_id" integer NOT NULL,
    "marketplace_module_id" "text" NOT NULL,
    "marketplace_order_id" "text" NOT NULL,
    "event_type" "text",
    "source_event_id" "text",
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "attempts" integer DEFAULT 0 NOT NULL,
    "last_error" "text",
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expires_at" timestamp with time zone DEFAULT ("now"() + '30 days'::interval) NOT NULL,
    "matched_pedido_id" bigint,
    "applied_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "pending_marketplace_enrichments_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'matched'::"text", 'applied'::"text", 'expired'::"text", 'failed'::"text"])))
);


ALTER TABLE "public"."pending_marketplace_enrichments" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pending_marketplace_enrichments_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pending_marketplace_enrichments_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pending_marketplace_enrichments_id_seq" OWNED BY "public"."pending_marketplace_enrichments"."id";



CREATE TABLE IF NOT EXISTS "public"."pending_order_reconciliations" (
    "id" bigint NOT NULL,
    "pedido_id" bigint,
    "erp_integration_id" integer,
    "erp_store_id" character varying(100),
    "erp_order_id" bigint,
    "marketplace_order_id" "text",
    "reason" "text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "attempts" integer DEFAULT 0 NOT NULL,
    "last_error" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolved_at" timestamp with time zone,
    "erp_order_number" "text",
    "marketplace_module_id" "text",
    "next_attempt_after" timestamp with time zone,
    CONSTRAINT "pending_order_reconciliations_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'matched'::"text", 'applied'::"text", 'expired'::"text", 'failed'::"text", 'skipped_terminal'::"text", 'skipped_duplicate'::"text"])))
);


ALTER TABLE "public"."pending_order_reconciliations" OWNER TO "postgres";


COMMENT ON COLUMN "public"."pending_order_reconciliations"."status" IS 'pending: aguardando resolucao | applied/matched: resolvido | failed: esgotou tentativas e exige intervencao | skipped_terminal: pedido cancelado/devolvido, nunca tera referencia de ERP e nao precisa ter | expired: janela vencida';



COMMENT ON COLUMN "public"."pending_order_reconciliations"."next_attempt_after" IS 'Momento a partir do qual vale tentar de novo. Backoff progressivo: o pedido demora entre 1 e ~97 min para aparecer no Bling, entao insistir a cada 60s gasta chamada de API sem ganhar nada depois das primeiras tentativas.';



CREATE SEQUENCE IF NOT EXISTS "public"."pending_order_reconciliations_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pending_order_reconciliations_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pending_order_reconciliations_id_seq" OWNED BY "public"."pending_order_reconciliations"."id";



CREATE TABLE IF NOT EXISTS "public"."perfis_fiscais" (
    "id" integer NOT NULL,
    "nome" "text" NOT NULL,
    "cst_icms" character varying(3),
    "cst_pis" character varying(2),
    "cst_cofins" character varying(2),
    "aliquota_icms" numeric(8,4),
    "aliquota_pis" numeric(8,4),
    "aliquota_cofins" numeric(8,4),
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."perfis_fiscais" OWNER TO "postgres";


ALTER TABLE "public"."perfis_fiscais" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."perfis_fiscais_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."permissoes_setor" (
    "id" integer NOT NULL,
    "setor_id" integer NOT NULL,
    "recurso_id" integer NOT NULL,
    "pode_ler" boolean DEFAULT false NOT NULL,
    "pode_criar" boolean DEFAULT false NOT NULL,
    "pode_editar" boolean DEFAULT false NOT NULL,
    "pode_excluir" boolean DEFAULT false NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."permissoes_setor" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."permissoes_setor_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."permissoes_setor_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."permissoes_setor_id_seq" OWNED BY "public"."permissoes_setor"."id";



CREATE TABLE IF NOT EXISTS "public"."personalizacoes_pedido" (
    "id" integer NOT NULL,
    "codigo_pedido" character varying(255) NOT NULL,
    "dados_cliente" "jsonb",
    "detalhes_personalizacao" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "shopee_order_sn" "text",
    "bling_id" "text",
    "item_id" "text",
    "item_description" "text",
    "customization_name" "text",
    "customization_initial" "text",
    "status" "text",
    "reasoning" "text",
    "name_source_message_id" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "item_pedido_id" integer
);


ALTER TABLE "public"."personalizacoes_pedido" OWNER TO "postgres";


COMMENT ON COLUMN "public"."personalizacoes_pedido"."item_pedido_id" IS 'Referência direta ao item em itens_pedido.id. Substitui match por descrição.';



CREATE SEQUENCE IF NOT EXISTS "public"."personalizacoes_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."personalizacoes_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."personalizacoes_pedido_id_seq" OWNED BY "public"."personalizacoes_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."plataformas" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "tipo" character varying(50),
    "ativa" boolean DEFAULT true,
    "configuracao" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."plataformas" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."plataformas_compat" AS
 SELECT "row_number"() OVER (ORDER BY "slug") AS "id",
    "name" AS "nome",
    NULL::"text" AS "descricao",
    "tipo",
    "is_active" AS "ativa",
    "config_schema" AS "configuracao",
    "created_at",
    "updated_at"
   FROM "public"."integration_modules"
  WHERE ("is_active" = true);


ALTER VIEW "public"."plataformas_compat" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."plataformas_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."plataformas_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."plataformas_id_seq" OWNED BY "public"."plataformas"."id";



CREATE TABLE IF NOT EXISTS "public"."pontos_coleta" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "horario_fechamento" time without time zone NOT NULL,
    "endereco" "text",
    "ativo" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."pontos_coleta" OWNER TO "postgres";


COMMENT ON TABLE "public"."pontos_coleta" IS 'Locais físicos para despacho de mercadorias (Agências, Pontos de Coleta, etc)';



COMMENT ON COLUMN "public"."pontos_coleta"."horario_fechamento" IS 'Hora em que o ponto fecha. Nao e hora de corte: corte e regra de pertencimento do lote, e quem tem corte e a janela. Para uma janela do tipo PONTO_COLETA, esta hora E o prazo de entrega.';



CREATE SEQUENCE IF NOT EXISTS "public"."pontos_coleta_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pontos_coleta_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pontos_coleta_id_seq" OWNED BY "public"."pontos_coleta"."id";



CREATE TABLE IF NOT EXISTS "public"."preferencias_ux_usuario" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" character varying(255) NOT NULL,
    "vista_padrao" character varying(50) DEFAULT 'KANBAN'::character varying,
    "ordenacao_padrao" character varying(50) DEFAULT 'PRIORIDADE'::character varying,
    "agrupamento_padrao" character varying(50),
    "filtros_salvos" "jsonb" DEFAULT '[]'::"jsonb",
    "atalhos_personalizados" "jsonb",
    "auto_fill_enabled" boolean DEFAULT true,
    "show_suggestions" boolean DEFAULT true,
    "validate_on_blur" boolean DEFAULT true,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."preferencias_ux_usuario" OWNER TO "postgres";


COMMENT ON TABLE "public"."preferencias_ux_usuario" IS 'Preferências de UX por usuário para personalizar a experiência e reduzir carga cognitiva';



COMMENT ON COLUMN "public"."preferencias_ux_usuario"."vista_padrao" IS 'Vista padrão: KANBAN, LISTA, CALENDARIO';



COMMENT ON COLUMN "public"."preferencias_ux_usuario"."ordenacao_padrao" IS 'Ordenação padrão: PRIORIDADE, HORARIO_CORTE, DATA_ENTREGA, DATA_CRIACAO';



COMMENT ON COLUMN "public"."preferencias_ux_usuario"."agrupamento_padrao" IS 'Agrupamento padrão: CANAL, MODALIDADE, SETOR, STATUS';



COMMENT ON COLUMN "public"."preferencias_ux_usuario"."filtros_salvos" IS 'Lista de presets de filtros salvos pelo usuário';



COMMENT ON COLUMN "public"."preferencias_ux_usuario"."atalhos_personalizados" IS 'Mapeamento de atalhos de teclado personalizados';



COMMENT ON COLUMN "public"."preferencias_ux_usuario"."auto_fill_enabled" IS 'Habilitar autopreenchimento inteligente de formulários';



CREATE TABLE IF NOT EXISTS "public"."previsao_consumo_demanda" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "demanda_id" integer NOT NULL,
    "produto_id" bigint NOT NULL,
    "quantidade_prevista" numeric(15,4) NOT NULL,
    "unidade" "text",
    "status" "text" DEFAULT 'PLANEJADO'::"text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."previsao_consumo_demanda" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."produto_alias_conflitos" (
    "id" bigint NOT NULL,
    "produto_id" integer NOT NULL,
    "codigo_externo" "text" NOT NULL,
    "produto_alias_id" integer,
    "observado_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolvido_em" timestamp with time zone
);


ALTER TABLE "public"."produto_alias_conflitos" OWNER TO "postgres";


ALTER TABLE "public"."produto_alias_conflitos" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."produto_alias_conflitos_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."produto_anuncios" (
    "id" bigint NOT NULL,
    "produto_id" integer,
    "integration_id" integer,
    "item_externo_id" "text" NOT NULL,
    "variacao_externa_id" "text",
    "sku_anuncio" "text",
    "titulo" "text",
    "url" "text",
    "status" "text" DEFAULT 'ativo'::"text" NOT NULL,
    "preco_publicado" numeric(15,4),
    "estoque_publicado" numeric(15,4),
    "estoque_buffer" numeric(15,4) DEFAULT 0 NOT NULL,
    "sincronizado_em" timestamp with time zone,
    "ultimo_erro" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "produto_anuncios_status_check" CHECK (("status" = ANY (ARRAY['ativo'::"text", 'pausado'::"text", 'encerrado'::"text"])))
);


ALTER TABLE "public"."produto_anuncios" OWNER TO "postgres";


ALTER TABLE "public"."produto_anuncios" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."produto_anuncios_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."produto_eixo_opcao_componentes" (
    "opcao_id" integer NOT NULL,
    "componente_produto_id" integer NOT NULL,
    "quantidade" numeric(15,6) DEFAULT 1 NOT NULL,
    CONSTRAINT "produto_eixo_opcao_componentes_quantidade_check" CHECK (("quantidade" > (0)::numeric))
);


ALTER TABLE "public"."produto_eixo_opcao_componentes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."produto_eixo_opcoes" (
    "id" integer NOT NULL,
    "eixo_id" integer NOT NULL,
    "codigo" "text" NOT NULL,
    "nome" "text" NOT NULL,
    "ativo" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."produto_eixo_opcoes" OWNER TO "postgres";


ALTER TABLE "public"."produto_eixo_opcoes" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."produto_eixo_opcoes_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."produto_eixos" (
    "id" integer NOT NULL,
    "codigo" "text" NOT NULL,
    "nome" "text" NOT NULL,
    "escopo" "text" DEFAULT 'produto'::"text" NOT NULL,
    "ordem_sku" integer,
    "ativo" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."produto_eixos" OWNER TO "postgres";


ALTER TABLE "public"."produto_eixos" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."produto_eixos_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."produto_pai_eixos" (
    "produto_pai_id" integer NOT NULL,
    "eixo_id" integer NOT NULL,
    "posicao" integer DEFAULT 0 NOT NULL
);


ALTER TABLE "public"."produto_pai_eixos" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."produto_precos" (
    "id" bigint NOT NULL,
    "produto_id" integer NOT NULL,
    "integration_id" integer,
    "tipo" "text" NOT NULL,
    "valor" numeric(15,4) NOT NULL,
    "vigencia_inicio" timestamp with time zone DEFAULT "now"() NOT NULL,
    "vigencia_fim" timestamp with time zone,
    CONSTRAINT "produto_precos_tipo_check" CHECK (("tipo" = ANY (ARRAY['padrao'::"text", 'promocional'::"text", 'minimo'::"text"]))),
    CONSTRAINT "produto_precos_valor_check" CHECK (("valor" >= (0)::numeric))
);


ALTER TABLE "public"."produto_precos" OWNER TO "postgres";


ALTER TABLE "public"."produto_precos" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."produto_precos_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."produto_sku_historico" (
    "id" bigint NOT NULL,
    "produto_id" integer NOT NULL,
    "sku_anterior" "text" NOT NULL,
    "sku_novo" "text" NOT NULL,
    "alterado_por" "uuid",
    "alterado_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "virou_apelido" boolean DEFAULT true NOT NULL
);


ALTER TABLE "public"."produto_sku_historico" OWNER TO "postgres";


ALTER TABLE "public"."produto_sku_historico" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."produto_sku_historico_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."produto_tags" (
    "produto_id" integer NOT NULL,
    "tag_id" integer NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."produto_tags" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."produto_variacao_backfill_revisao" (
    "produto_id" integer NOT NULL,
    "sku_observado" "text" NOT NULL,
    "motivo" "text" NOT NULL,
    "criado_em" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolvido_em" timestamp with time zone
);


ALTER TABLE "public"."produto_variacao_backfill_revisao" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."produto_variacao_valores" (
    "produto_id" integer NOT NULL,
    "eixo_id" integer NOT NULL,
    "opcao_id" integer NOT NULL
);


ALTER TABLE "public"."produto_variacao_valores" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."produtos_externos" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "codigo_externo" character varying(255) NOT NULL,
    "plataforma" character varying(50),
    "metadados" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "tipo" "text" DEFAULT 'SKU'::"text" NOT NULL,
    CONSTRAINT "produtos_externos_tipo_check" CHECK (("tipo" = ANY (ARRAY['SKU'::"text", 'ID'::"text", 'NOME'::"text"])))
);


ALTER TABLE "public"."produtos_externos" OWNER TO "postgres";


COMMENT ON TABLE "public"."produtos_externos" IS 'Apelidos externos de um produto: SKU, ID ou nome pelo qual ele aparece em cada marketplace. Destino unico do mapeamento marketplace -> catalogo interno (fase B4).';



COMMENT ON COLUMN "public"."produtos_externos"."plataforma" IS 'Slug da plataforma (shopee, mercadolivre, bling...). NULL = apelido valido em qualquer origem.';



COMMENT ON COLUMN "public"."produtos_externos"."tipo" IS 'SKU, ID ou NOME. Define a precedencia na resolucao: SKU vence ID, que vence NOME.';



CREATE SEQUENCE IF NOT EXISTS "public"."produtos_externos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."produtos_externos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."produtos_externos_id_seq" OWNED BY "public"."produtos_externos"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."produtos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."produtos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."produtos_id_seq" OWNED BY "public"."produtos"."id";



CREATE TABLE IF NOT EXISTS "public"."recursos" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" character varying(255),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."recursos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."recursos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."recursos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."recursos_id_seq" OWNED BY "public"."recursos"."id";



CREATE TABLE IF NOT EXISTS "public"."recursos_produtivos" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "tipo" character varying(50),
    "descricao" "text",
    "capacidade" "jsonb",
    "status" character varying(50) DEFAULT 'ATIVO'::character varying,
    "dados_tecnicos" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."recursos_produtivos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."recursos_produtivos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."recursos_produtivos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."recursos_produtivos_id_seq" OWNED BY "public"."recursos_produtivos"."id";



CREATE TABLE IF NOT EXISTS "public"."regra_logistica_modalidades" (
    "regra_id" bigint NOT NULL,
    "modalidade_id" integer NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."regra_logistica_modalidades" OWNER TO "postgres";


COMMENT ON TABLE "public"."regra_logistica_modalidades" IS 'Quais modalidades uma janela de despacho atende. Existe porque canais diferentes podem seguir a mesma regra e sair no mesmo lote (Shopee Xpress e Retirada pelo Comprador). Antes disso, compartilhar janela so era possivel classificando um canal como o outro.';



CREATE SEQUENCE IF NOT EXISTS "public"."regras_classificacao_modalidade_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."regras_classificacao_modalidade_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."regras_classificacao_modalidade_id_seq" OWNED BY "public"."regras_classificacao_modalidade"."id";



CREATE TABLE IF NOT EXISTS "public"."regras_consolidacao_canal" (
    "id" bigint NOT NULL,
    "canal_venda_id" bigint,
    "modalidade" character varying(50),
    "agrupar_por_produto" boolean DEFAULT true,
    "agrupar_por_miolo" boolean DEFAULT true,
    "agrupar_por_data_entrega" boolean DEFAULT true,
    "janela_agrupamento_horas" integer DEFAULT 4,
    "comportamento_pos_edicao" character varying(30) DEFAULT 'ADICIONAR_COM_SINALIZACAO'::character varying,
    "comportamento_pos_publicacao" character varying(30) DEFAULT 'CRIAR_NOVO_RASCUNHO'::character varying,
    "ativo" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "regras_consolidacao_canal_comportamento_pos_edicao_check" CHECK ((("comportamento_pos_edicao")::"text" = ANY ((ARRAY['ADICIONAR_COM_SINALIZACAO'::character varying, 'CRIAR_NOVO_RASCUNHO'::character varying])::"text"[]))),
    CONSTRAINT "regras_consolidacao_canal_comportamento_pos_publicacao_check" CHECK ((("comportamento_pos_publicacao")::"text" = ANY ((ARRAY['CRIAR_NOVO_RASCUNHO'::character varying, 'SUGERIR_FUSAO'::character varying])::"text"[]))),
    CONSTRAINT "regras_consolidacao_canal_modalidade_check" CHECK ((("modalidade")::"text" = ANY ((ARRAY['STANDARD'::character varying, 'EXPRESS'::character varying, 'FULFILLMENT'::character varying, 'RETIRADA'::character varying])::"text"[])))
);


ALTER TABLE "public"."regras_consolidacao_canal" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."regras_consolidacao_canal_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."regras_consolidacao_canal_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."regras_consolidacao_canal_id_seq" OWNED BY "public"."regras_consolidacao_canal"."id";



CREATE TABLE IF NOT EXISTS "public"."regras_logisticas_canal" (
    "id" integer NOT NULL,
    "canal_venda_id" integer NOT NULL,
    "modalidade" character varying(50) NOT NULL,
    "tipo_envio" character varying(50) NOT NULL,
    "horario_limite" time without time zone NOT NULL,
    "ponto_coleta_id" integer,
    "prioridade_uso" integer DEFAULT 1,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "marketplace_integration_id" integer
);


ALTER TABLE "public"."regras_logisticas_canal" OWNER TO "postgres";


COMMENT ON TABLE "public"."regras_logisticas_canal" IS 'Regras de janelas de despacho e backups por canal e modalidade';



COMMENT ON COLUMN "public"."regras_logisticas_canal"."modalidade" IS 'Modalidade logística vinculada (STANDARD, EXPRESS, FULFILLMENT, RETIRADA)';



COMMENT ON COLUMN "public"."regras_logisticas_canal"."tipo_envio" IS 'Tipo da janela (COLETA_LOCAL para quando buscam na empresa, PONTO_COLETA para quando levamos)';



CREATE SEQUENCE IF NOT EXISTS "public"."regras_logisticas_canal_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."regras_logisticas_canal_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."regras_logisticas_canal_id_seq" OWNED BY "public"."regras_logisticas_canal"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."regras_logisticas_integracao_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."regras_logisticas_integracao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."regras_logisticas_integracao_id_seq" OWNED BY "public"."regras_logisticas_integracao"."id";



CREATE TABLE IF NOT EXISTS "public"."regras_priorizacao" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "descricao" "text",
    "condicoes" "jsonb" NOT NULL,
    "acao" "jsonb" NOT NULL,
    "ativa" boolean DEFAULT true,
    "prioridade_regra" integer DEFAULT 0,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."regras_priorizacao" OWNER TO "postgres";


COMMENT ON TABLE "public"."regras_priorizacao" IS 'Regras configuráveis para priorização e ordenação de demandas de produção';



COMMENT ON COLUMN "public"."regras_priorizacao"."condicoes" IS 'Condições para aplicar a regra: {canal_venda_ids, plataforma_nomes, modalidade_logistica, tipo_demanda, faixa_quantidade, horario_corte}';



COMMENT ON COLUMN "public"."regras_priorizacao"."acao" IS 'Ação de priorização: {tipo: ADD_SCORE|SET_PRIORIDADE|MOVER_TOPO|ADIAR, valor, fatores}';



COMMENT ON COLUMN "public"."regras_priorizacao"."prioridade_regra" IS 'Prioridade da regra para resolver conflitos (maior = mais prioritária)';



CREATE SEQUENCE IF NOT EXISTS "public"."regras_priorizacao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."regras_priorizacao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."regras_priorizacao_id_seq" OWNED BY "public"."regras_priorizacao"."id";



CREATE TABLE IF NOT EXISTS "public"."setores" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "ativo" boolean DEFAULT true NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."setores" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."setores_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."setores_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."setores_id_seq" OWNED BY "public"."setores"."id";



CREATE TABLE IF NOT EXISTS "public"."sinalizacoes_demanda" (
    "id" integer NOT NULL,
    "demanda_id" integer NOT NULL,
    "tipo" character varying(50) NOT NULL,
    "severidade" character varying(20) NOT NULL,
    "dados" "jsonb" DEFAULT '{}'::"jsonb",
    "visivel" boolean DEFAULT true,
    "lido" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."sinalizacoes_demanda" OWNER TO "postgres";


COMMENT ON TABLE "public"."sinalizacoes_demanda" IS 'Sinalizações visuais para demandas (alertas, badges, indicadores de contexto)';



COMMENT ON COLUMN "public"."sinalizacoes_demanda"."tipo" IS 'Tipo: FLEX, FULFILLMENT, HORARIO_CORTE_PROXIMO, PEDIDO_VINCULADO, INTEGRACAO_ERRO, ESTOQUE_INSUFICIENTE, PRODUCAO_ATRASADA';



COMMENT ON COLUMN "public"."sinalizacoes_demanda"."severidade" IS 'Severidade: INFO, ATENCAO, CRITICO';



COMMENT ON COLUMN "public"."sinalizacoes_demanda"."dados" IS 'Dados contextuais específicos do tipo de sinalização';



CREATE SEQUENCE IF NOT EXISTS "public"."sinalizacoes_demanda_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."sinalizacoes_demanda_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."sinalizacoes_demanda_id_seq" OWNED BY "public"."sinalizacoes_demanda"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."situacoes_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."situacoes_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."situacoes_pedido_id_seq" OWNED BY "public"."situacoes_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."sync_status_batches" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "pedido_ids" bigint[] NOT NULL,
    "total" integer NOT NULL,
    "sucesso" integer DEFAULT 0,
    "falha" integer DEFAULT 0,
    "status" "text" DEFAULT 'PENDENTE'::"text",
    "iniciado_em" timestamp with time zone DEFAULT "now"(),
    "finalizado_em" timestamp with time zone
);


ALTER TABLE "public"."sync_status_batches" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."sync_status_errors" (
    "id" bigint NOT NULL,
    "batch_id" "uuid",
    "pedido_id" bigint NOT NULL,
    "bling_id" bigint,
    "erro" "text",
    "tentado_em" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."sync_status_errors" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."sync_status_errors_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."sync_status_errors_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."sync_status_errors_id_seq" OWNED BY "public"."sync_status_errors"."id";



CREATE TABLE IF NOT EXISTS "public"."system_events_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "severity" "text" DEFAULT 'ERROR'::"text" NOT NULL,
    "category" "text" NOT NULL,
    "action" "text",
    "message" "text" NOT NULL,
    "reference_id" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "resolved" boolean DEFAULT false,
    "user_id" "text"
);


ALTER TABLE "public"."system_events_log" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tags" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "cor" character varying(7),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."tags" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."tags_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tags_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tags_id_seq" OWNED BY "public"."tags"."id";



CREATE TABLE IF NOT EXISTS "public"."task_daily_stats" (
    "dia" "date" NOT NULL,
    "task_name" "text" NOT NULL,
    "task_type" "text" DEFAULT '(sem tipo)'::"text" NOT NULL,
    "status" "text" DEFAULT '(sem status)'::"text" NOT NULL,
    "total" bigint NOT NULL,
    "duracao_ms_media" numeric,
    "duracao_ms_max" numeric,
    "atualizado_em" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."task_daily_stats" OWNER TO "postgres";


COMMENT ON TABLE "public"."task_daily_stats" IS 'Agregado diario permanente de task_execution_logs. Substitui o log bruto, que passa a ter retencao de 1 dia.';



CREATE TABLE IF NOT EXISTS "public"."task_execution_logs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "task_name" character varying(100) NOT NULL,
    "status" character varying(50) DEFAULT 'PENDING'::character varying NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "started_at" timestamp with time zone,
    "finished_at" timestamp with time zone,
    "error_message" "text",
    "task_type" character varying(100),
    "correlation_id" character varying(100),
    "retry_count" integer DEFAULT 0,
    "last_retry_at" timestamp with time zone,
    "next_retry_at" timestamp with time zone
);


ALTER TABLE "public"."task_execution_logs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."templates_obs_canal" (
    "id" integer NOT NULL,
    "canal_venda_id" integer,
    "nome" character varying(255) NOT NULL,
    "template" "text" NOT NULL,
    "variaveis_suportadas" "text"[] DEFAULT ARRAY[]::"text"[],
    "is_default" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."templates_obs_canal" OWNER TO "postgres";


COMMENT ON TABLE "public"."templates_obs_canal" IS 'Templates de observações pré-configurados por canal de venda para autopreenchimento';



COMMENT ON COLUMN "public"."templates_obs_canal"."template" IS 'Template de texto com variáveis substituíveis (ex: {{pedido_numero}}, {{data_entrega}})';



COMMENT ON COLUMN "public"."templates_obs_canal"."variaveis_suportadas" IS 'Lista de variáveis suportadas no template';



COMMENT ON COLUMN "public"."templates_obs_canal"."is_default" IS 'Indica se este é o template padrão para o canal (apenas um por canal)';



CREATE SEQUENCE IF NOT EXISTS "public"."templates_obs_canal_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."templates_obs_canal_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."templates_obs_canal_id_seq" OWNED BY "public"."templates_obs_canal"."id";



CREATE TABLE IF NOT EXISTS "public"."transicoes_situacao" (
    "id" integer NOT NULL,
    "situacao_origem_id" integer NOT NULL,
    "situacao_destino_id" integer NOT NULL,
    "regra_permissao" character varying(100),
    "descricao_transicao" "text",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."transicoes_situacao" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."transicoes_situacao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."transicoes_situacao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."transicoes_situacao_id_seq" OWNED BY "public"."transicoes_situacao"."id";



CREATE TABLE IF NOT EXISTS "public"."unidades_medida" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "abreviacao" character varying(20),
    "descricao" "text",
    "tipo" character varying(50),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."unidades_medida" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."unidades_medida_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."unidades_medida_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."unidades_medida_id_seq" OWNED BY "public"."unidades_medida"."id";



CREATE TABLE IF NOT EXISTS "public"."usuarios" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "email" character varying(120) NOT NULL,
    "senha_hash" character varying(256),
    "setor_id" integer NOT NULL,
    "ativo" boolean DEFAULT true NOT NULL,
    "is_admin" boolean DEFAULT false NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "last_login" timestamp without time zone
);


ALTER TABLE "public"."usuarios" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."usuarios_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."usuarios_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."usuarios_id_seq" OWNED BY "public"."usuarios"."id";



CREATE OR REPLACE VIEW "public"."v_auditoria_bom_componentes_invalidos" AS
 SELECT "ft"."id" AS "ficha_tecnica_id",
    "ft"."produto_pai_id",
    "pai"."sku" AS "produto_pai_sku",
    "pai"."nome" AS "produto_pai_nome",
    "pai"."tipo_produto" AS "produto_pai_tipo",
    "ft"."componente_id",
    "componente"."sku" AS "componente_sku",
    "componente"."nome" AS "componente_nome",
    "componente"."tipo_produto" AS "componente_tipo",
    "ft"."quantidade_necessaria",
        CASE
            WHEN ("componente"."tipo_produto" = 'PRODUTO_ACABADO'::"public"."tipo_produto_enum") THEN 'COMPONENTE_PRODUTO_ACABADO'::"text"
            ELSE 'OK'::"text"
        END AS "status_auditoria"
   FROM (("public"."ficha_tecnica" "ft"
     LEFT JOIN "public"."produtos" "pai" ON (("pai"."id" = "ft"."produto_pai_id")))
     LEFT JOIN "public"."produtos" "componente" ON (("componente"."id" = "ft"."componente_id")))
  WHERE ("componente"."tipo_produto" = 'PRODUTO_ACABADO'::"public"."tipo_produto_enum");


ALTER VIEW "public"."v_auditoria_bom_componentes_invalidos" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."v_auditoria_variacoes_tipo_divergente" AS
 SELECT "v"."id" AS "variacao_id",
    "v"."sku" AS "variacao_sku",
    "v"."nome" AS "variacao_nome",
    "v"."tipo_produto" AS "variacao_tipo_produto",
    "v"."tipo_material" AS "variacao_tipo_material",
    "v"."status" AS "variacao_status",
    "p"."id" AS "pai_id",
    "p"."sku" AS "pai_sku",
    "p"."nome" AS "pai_nome",
    "p"."tipo_produto" AS "pai_tipo_produto",
    "p"."tipo_material" AS "pai_tipo_material",
    "v"."formato" AS "variacao_formato",
    "v"."herdar_dados_pai",
    "v"."created_at" AS "variacao_created_at",
    "v"."updated_at" AS "variacao_updated_at"
   FROM ("public"."produtos" "v"
     JOIN "public"."produtos" "p" ON (("p"."id" = "v"."parent_id")))
  WHERE (("v"."parent_id" IS NOT NULL) AND ("v"."tipo_produto" IS DISTINCT FROM "p"."tipo_produto"));


ALTER VIEW "public"."v_auditoria_variacoes_tipo_divergente" OWNER TO "postgres";


COMMENT ON VIEW "public"."v_auditoria_variacoes_tipo_divergente" IS 'Auditoria: lista variacoes cujo tipo_produto difere do pai. Usada antes do backfill (passo 2) e do trigger de invariante (passo 3). Apenas leitura.';



CREATE OR REPLACE VIEW "public"."v_canais_coleta_dia" WITH ("security_invoker"='on') AS
 SELECT "c"."id",
    "c"."nome",
    "to_char"(("c"."horario_coleta")::interval, 'HH24:MI'::"text") AS "horario_coleta",
    "c"."flex",
    "c"."fulfillment",
    "c"."color",
    "c"."plataforma_id",
    "p"."nome" AS "plataforma_nome",
        CASE
            WHEN ((EXTRACT(hour FROM "c"."horario_coleta") >= (6)::numeric) AND (EXTRACT(hour FROM "c"."horario_coleta") <= (12)::numeric)) THEN 'MANHA'::"text"
            WHEN ((EXTRACT(hour FROM "c"."horario_coleta") >= (13)::numeric) AND (EXTRACT(hour FROM "c"."horario_coleta") <= (18)::numeric)) THEN 'TARDE'::"text"
            ELSE 'NOITE'::"text"
        END AS "periodo_coleta",
    ((EXTRACT(hour FROM "c"."horario_coleta") * (60)::numeric) + EXTRACT(minute FROM "c"."horario_coleta")) AS "horario_minutos"
   FROM ("public"."canais_venda" "c"
     LEFT JOIN "public"."plataformas" "p" ON (("c"."plataforma_id" = "p"."id")))
  WHERE (("c"."ativo" = true) AND ("c"."horario_coleta" IS NOT NULL));


ALTER VIEW "public"."v_canais_coleta_dia" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."v_candidatos_verificacao_estoque" AS
 SELECT "i"."id" AS "item_id",
    "i"."demanda_id",
    "d"."status" AS "status_demanda",
    "i"."sku" AS "sku_origem",
    ("p"."sku")::"text" AS "produto",
    ("p"."tipo_produto")::"text" AS "tipo",
    "i"."quantidade",
    "s"."niveis",
    "s"."movimentos_previstos",
    "s"."bloqueados",
        CASE
            WHEN ("s"."bloqueados" > 0) THEN (('BLOQUEADO — '::"text" || "s"."bloqueados") || ' produto(s) sem ficha técnica (regra B5)'::"text")
            WHEN (("d"."status")::"text" = 'RASCUNHO'::"text") THEN 'APTO — demanda em rascunho, menor impacto'::"text"
            ELSE ('APTO — atenção: demanda '::"text" || (COALESCE("d"."status", 'sem status'::character varying))::"text")
        END AS "veredito"
   FROM ((("public"."itens_demanda" "i"
     JOIN "public"."produtos" "p" ON (("p"."id" = "i"."produto_id")))
     LEFT JOIN "public"."demandas_producao" "d" ON (("d"."id" = "i"."demanda_id")))
     CROSS JOIN LATERAL ( SELECT ("sum"("simular_reconciliacao_item"."movimentos_gerados"))::integer AS "movimentos_previstos",
            "max"("simular_reconciliacao_item"."nivel") AS "niveis",
            "count"(*) FILTER (WHERE ("simular_reconciliacao_item"."movimento" = 'BLOQUEADO'::"text")) AS "bloqueados"
           FROM "public"."simular_reconciliacao_item"("i"."id") "simular_reconciliacao_item"("nivel", "caminho", "produto_id", "sku", "tipo_produto", "movimento", "movimentos_gerados", "quantidade", "saldo_atual", "observacao")) "s")
  WHERE (COALESCE("i"."finalizados_qtd", (0)::numeric) = (0)::numeric);


ALTER VIEW "public"."v_candidatos_verificacao_estoque" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."v_itens_demanda_mapeamento" AS
 SELECT "i"."id" AS "item_id",
    "i"."demanda_id",
    "i"."sku",
    "i"."descricao",
    "r"."produto_id",
    "r"."produto_sku",
    "r"."variacao",
    "r"."miolo_id",
    "r"."miolo_sku",
    COALESCE("r"."origem", 'nao_resolvido'::"text") AS "origem",
    (COALESCE("r"."origem", 'nao_resolvido'::"text") = ANY (ARRAY['miolo_por_fallback_legado'::"text", 'nao_resolvido'::"text"])) AS "precisa_cadastro"
   FROM ("public"."itens_demanda" "i"
     LEFT JOIN LATERAL "public"."resolver_produto_completo"(("i"."sku")::"text") "r"("produto_id", "produto_sku", "produto_nome", "variacao", "miolo_id", "miolo_sku", "miolo_nome", "origem") ON (true));


ALTER VIEW "public"."v_itens_demanda_mapeamento" OWNER TO "postgres";


COMMENT ON VIEW "public"."v_itens_demanda_mapeamento" IS 'Como cada item de demanda foi identificado. precisa_cadastro marca o que so resolveu por heuristica do legado ou nao resolveu — a fila de trabalho para deixar o cadastro consistente.';



CREATE OR REPLACE VIEW "public"."v_pedido_demanda_rastreamento" AS
 SELECT "p"."id" AS "pedido_id",
    "p"."numero_pedido",
    "p"."codigo_pedido_externo",
    "p"."origem" AS "pedido_origem",
    "p"."is_flex" AS "pedido_is_flex",
    "p"."personalizado" AS "pedido_personalizado",
    "p"."data_venda",
    "p"."cliente_nome",
    "p"."canal_venda_id",
    "p"."situacao_pedido_id",
    ( SELECT "dp"."id"
           FROM ("public"."demandas_pedidos" "dpiv"
             JOIN "public"."demandas_producao" "dp" ON (("dpiv"."demanda_id" = "dp"."id")))
          WHERE ("dpiv"."pedido_id" = "p"."id")
          ORDER BY "dp"."created_at" DESC
         LIMIT 1) AS "demanda_id",
    ( SELECT "dp"."demanda_id"
           FROM ("public"."demandas_pedidos" "dpiv"
             JOIN "public"."demandas_producao" "dp" ON (("dpiv"."demanda_id" = "dp"."id")))
          WHERE ("dpiv"."pedido_id" = "p"."id")
          ORDER BY "dp"."created_at" DESC
         LIMIT 1) AS "demanda_numero",
    ( SELECT "dp"."status"
           FROM ("public"."demandas_pedidos" "dpiv"
             JOIN "public"."demandas_producao" "dp" ON (("dpiv"."demanda_id" = "dp"."id")))
          WHERE ("dpiv"."pedido_id" = "p"."id")
          ORDER BY "dp"."created_at" DESC
         LIMIT 1) AS "demanda_status",
    ( SELECT "count"(*) AS "count"
           FROM "public"."demandas_pedidos" "dpiv"
          WHERE ("dpiv"."pedido_id" = "p"."id")) AS "total_demandas",
    "cv"."nome" AS "canal_venda_nome",
    "sp"."nome" AS "situacao_pedido_nome",
    "sp"."cor_status" AS "situacao_pedido_cor"
   FROM (("public"."pedidos" "p"
     LEFT JOIN "public"."canais_venda" "cv" ON (("p"."canal_venda_id" = "cv"."id")))
     LEFT JOIN "public"."situacoes_pedido" "sp" ON (("p"."situacao_pedido_id" = "sp"."id")));


ALTER VIEW "public"."v_pedido_demanda_rastreamento" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_alocacoes_por_demanda" WITH ("security_invoker"='on') AS
 SELECT "demanda_id",
    "count"(DISTINCT "item_id") AS "itens_count",
    "count"(DISTINCT "produto_id") AS "produtos_count",
    "sum"(
        CASE
            WHEN (("status")::"text" <> 'CANCELADA'::"text") THEN "quantidade_alocada"
            ELSE (0)::numeric
        END) AS "total_alocado_geral"
   FROM "public"."demanda_alocacoes_estoque"
  GROUP BY "demanda_id";


ALTER VIEW "public"."view_alocacoes_por_demanda" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_alocacoes_por_item" AS
 SELECT "item_id",
    "demanda_id",
    "produto_id",
    "sum"(
        CASE
            WHEN (("status")::"text" <> 'CANCELADA'::"text") THEN "quantidade_alocada"
            ELSE (0)::numeric
        END) AS "total_alocado"
   FROM "public"."demanda_alocacoes_estoque"
  GROUP BY "item_id", "demanda_id", "produto_id";


ALTER VIEW "public"."view_alocacoes_por_item" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_auditoria_tipo_produto" AS
 SELECT "id",
    "nome" AS "produto_nome",
    "sku",
    "tipo_material",
    "tipo_produto",
        CASE
            WHEN (("tipo_produto" IS NULL) AND ("tipo_material" IS NOT NULL)) THEN 'ERRO_CONVERSAO'::"text"
            WHEN (("tipo_produto" IS NULL) AND ("tipo_material" IS NULL)) THEN 'SEM_CLASSIFICACAO'::"text"
            WHEN (("tipo_material" IS NULL) AND ("tipo_produto" IS NOT NULL)) THEN 'OK_MANUAL'::"text"
            WHEN (((("tipo_material")::"text" = 'materia_prima'::"text") AND ("tipo_produto" = 'MATERIA_PRIMA'::"public"."tipo_produto_enum")) OR ((("tipo_material")::"text" = 'intermediario'::"text") AND ("tipo_produto" = 'INTERMEDIARIO'::"public"."tipo_produto_enum")) OR ((("tipo_material")::"text" = 'produto_acabado'::"text") AND ("tipo_produto" = 'PRODUTO_ACABADO'::"public"."tipo_produto_enum")) OR ((("tipo_material")::"text" = 'servico'::"text") AND ("tipo_produto" = 'SERVICO'::"public"."tipo_produto_enum"))) THEN 'OK'::"text"
            ELSE 'DIVERGENTE'::"text"
        END AS "status_conferencia",
    "updated_at"
   FROM "public"."produtos" "p"
  ORDER BY "id";


ALTER VIEW "public"."view_auditoria_tipo_produto" OWNER TO "postgres";


COMMENT ON VIEW "public"."view_auditoria_tipo_produto" IS 'Auditoria da conversão de tipo_material para tipo_produto.';



CREATE OR REPLACE VIEW "public"."view_consolidado_previsao_materiais" AS
 SELECT "p"."id" AS "produto_id",
    "p"."sku",
    "p"."nome" AS "produto_nome",
    "p"."unidade_medida_id",
    "um"."nome" AS "unidade_nome",
    "sum"("pre"."quantidade_prevista") AS "total_necessario",
    "count"(DISTINCT "pre"."demanda_id") AS "num_demandas"
   FROM ((("public"."previsao_consumo_demanda" "pre"
     JOIN "public"."produtos" "p" ON (("pre"."produto_id" = "p"."id")))
     LEFT JOIN "public"."unidades_medida" "um" ON (("p"."unidade_medida_id" = "um"."id")))
     JOIN "public"."demandas_producao" "d" ON (("pre"."demanda_id" = "d"."id")))
  WHERE ((("d"."status")::"text" <> ALL ((ARRAY['CONCLUIDO'::character varying, 'CANCELADO'::character varying])::"text"[])) AND ("pre"."status" = 'PLANEJADO'::"text"))
  GROUP BY "p"."id", "p"."sku", "p"."nome", "p"."unidade_medida_id", "um"."nome";


ALTER VIEW "public"."view_consolidado_previsao_materiais" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_consolidado_producao" AS
 SELECT "i"."id" AS "item_id",
    "i"."demanda_id",
    "d"."descricao" AS "demanda_nome",
    "d"."data_entrega",
    "d"."horario_coleta",
    "i"."sku",
    "i"."descricao" AS "item_nome",
    "i"."quantidade" AS "qtd_total",
    "i"."capas_impressas_qtd",
    "i"."capas_produzidas_qtd" AS "capas_prontas",
    "i"."miolos_prontos_retirada_qtd" AS "miolos_prontos",
    COALESCE("i"."expedicao_capas_retiradas_qtd", (0)::numeric) AS "expedicao_capas_retiradas_qtd",
    COALESCE("i"."expedicao_miolos_retirados_qtd", (0)::numeric) AS "expedicao_miolos_retirados_qtd",
    (LEAST((COALESCE("i"."capas_produzidas_qtd", (0)::numeric) - COALESCE("i"."expedicao_capas_retiradas_qtd", (0)::numeric)), (COALESCE("i"."miolos_prontos_retirada_qtd", (0)::numeric) - COALESCE("i"."expedicao_miolos_retirados_qtd", (0)::numeric))))::numeric(15,4) AS "match_disponivel",
    "d"."status" AS "demanda_status",
    "i"."status_item",
        CASE
            WHEN ("d"."prioridade_manual" >= 100) THEN 'URGENTE'::"text"
            WHEN "d"."is_flex" THEN 'FLEX'::"text"
            ELSE 'NORMAL'::"text"
        END AS "trilha",
    "d"."updated_at" AS "status_sincronia"
   FROM ("public"."itens_demanda" "i"
     JOIN "public"."demandas_producao" "d" ON (("i"."demanda_id" = "d"."id")))
  WHERE (("d"."status")::"text" <> ALL (ARRAY[('Finalizado'::character varying)::"text", ('Coletado'::character varying)::"text", ('Cancelado'::character varying)::"text"]));


ALTER VIEW "public"."view_consolidado_producao" OWNER TO "postgres";


COMMENT ON VIEW "public"."view_consolidado_producao" IS 'View consolidada de produção com cálculo corrigido de match_disponivel.
Agora considera as retiradas de expedição para determinar quantidades disponíveis para montagem.';



CREATE OR REPLACE VIEW "public"."view_ledger_completo" AS
 SELECT "dep"."id",
    "dep"."item_id",
    "id"."descricao" AS "item_descricao",
    "id"."sku" AS "item_sku",
    "dp"."id" AS "demanda_id",
    "dp"."descricao" AS "demanda_descricao",
    "dep"."estagio",
    "dep"."tipo_movimentacao",
    "dep"."produto_id",
    "p"."nome" AS "produto_nome",
    "p"."sku" AS "produto_sku",
    "p"."tipo_produto",
    "dep"."quantidade",
    "dep"."saldo_acumulado",
    "dep"."correlation_id",
    "dep"."usuario_id",
    "u"."nome" AS "usuario_responsavel",
    "dep"."metadata",
    "dep"."created_at",
    "dep"."updated_at"
   FROM (((("public"."demanda_estoque_processado" "dep"
     JOIN "public"."itens_demanda" "id" ON (("dep"."item_id" = "id"."id")))
     JOIN "public"."demandas_producao" "dp" ON (("dep"."demanda_id" = "dp"."id")))
     LEFT JOIN "public"."produtos" "p" ON (("dep"."produto_id" = "p"."id")))
     LEFT JOIN "public"."usuarios" "u" ON (("dep"."usuario_id" = "u"."id")))
  ORDER BY "dep"."created_at" DESC;


ALTER VIEW "public"."view_ledger_completo" OWNER TO "postgres";


COMMENT ON VIEW "public"."view_ledger_completo" IS 'View consolidada do ledger de estoque para auditoria. Mostra todas as movimentações com detalhes de demanda, item, produto e usuário.';



CREATE OR REPLACE VIEW "public"."view_mensagens_chat" AS
 WITH "processed_msgs" AS (
         SELECT "mensagem_chat_shopee"."id",
            "mensagem_chat_shopee"."from_user_name",
            "mensagem_chat_shopee"."to_user_name",
            "mensagem_chat_shopee"."created_at",
            "mensagem_chat_shopee"."type",
                CASE
                    WHEN ("jsonb_typeof"("mensagem_chat_shopee"."content") = 'string'::"text") THEN (("mensagem_chat_shopee"."content" #>> '{}'::"text"[]))::"jsonb"
                    ELSE "mensagem_chat_shopee"."content"
                END AS "content_json"
           FROM "public"."mensagem_chat_shopee"
        )
 SELECT "id",
    "from_user_name",
    "to_user_name",
    "content_json" AS "content",
    "created_at",
    "type",
        CASE
            WHEN ("type" = 'text'::"text") THEN ("content_json" ->> 'text'::"text")
            WHEN ("type" = 'new_faq'::"text") THEN ("content_json" ->> 'opening'::"text")
            WHEN ("type" = 'notification'::"text") THEN ("content_json" ->> 'notification_for_sender'::"text")
            WHEN (("content_json" ->> 'sticker_id'::"text") IS NOT NULL) THEN '[figurinha]'::"text"
            ELSE COALESCE(("content_json" ->> 'text'::"text"), 'Mensagem sem conteúdo'::"text")
        END AS "display_content"
   FROM "processed_msgs"
  WHERE ("type" <> ALL (ARRAY['faq_unsupported'::"text", 'faq_question_list'::"text", 'faq_category_choice'::"text", 'faq_feedback_prompt'::"text"]));


ALTER VIEW "public"."view_mensagens_chat" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_mensagens_chat_ai" WITH ("security_invoker"='true') AS
 WITH "parsed" AS (
         SELECT "m"."id",
            "m"."from_user_name",
            "m"."to_user_name",
            COALESCE("m"."created_at", ("m"."created_timestamp" AT TIME ZONE 'America/Sao_Paulo'::"text")) AS "created_at",
            COALESCE(NULLIF("m"."type", ''::"text"), 'text'::"text") AS "type",
                CASE
                    WHEN ("jsonb_typeof"("m"."content") = 'string'::"text") THEN (("m"."content" #>> '{}'::"text"[]))::"jsonb"
                    ELSE "m"."content"
                END AS "content_json"
           FROM "public"."mensagem_chat_shopee" "m"
        ), "normalized" AS (
         SELECT "p"."id",
            "p"."from_user_name",
            "p"."to_user_name",
            "p"."created_at",
            "p"."type",
            TRIM(BOTH FROM COALESCE(
                CASE
                    WHEN ("p"."type" = 'text'::"text") THEN ("p"."content_json" ->> 'text'::"text")
                    ELSE NULL::"text"
                END,
                CASE
                    WHEN ("p"."type" = 'new_faq'::"text") THEN ("p"."content_json" ->> 'opening'::"text")
                    ELSE NULL::"text"
                END,
                CASE
                    WHEN ("p"."type" = 'notification'::"text") THEN ("p"."content_json" ->> 'notification_for_sender'::"text")
                    ELSE NULL::"text"
                END, ("p"."content_json" ->> 'text'::"text"), ("p"."content_json" ->> 'url'::"text"),
                CASE
                    WHEN ("p"."content_json" ? 'sticker_id'::"text") THEN '[figurinha]'::"text"
                    ELSE NULL::"text"
                END, NULLIF(("p"."content_json")::"text", '{}'::"text"))) AS "display_content"
           FROM "parsed" "p"
        )
 SELECT "id",
    "from_user_name",
    "to_user_name",
    "created_at",
    "type",
    "left"("display_content", 1000) AS "display_content"
   FROM "normalized" "n"
  WHERE (("type" <> ALL (ARRAY['faq_unsupported'::"text", 'faq_question_list'::"text", 'faq_category_choice'::"text", 'faq_feedback_prompt'::"text", 'bundle_message'::"text"])) AND (COALESCE("display_content", ''::"text") <> ''::"text"));


ALTER VIEW "public"."view_mensagens_chat_ai" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_mensagens_chat_ai_v2" WITH ("security_invoker"='true') AS
 SELECT "m"."id",
    "m"."installed_integration_id",
    "m"."from_id",
    "m"."to_id",
    "m"."from_user_name",
    "m"."to_user_name",
    "m"."conversation_id",
    "m"."created_at",
    "m"."type",
    "m"."content",
    "m"."source_content",
    "v"."display_content"
   FROM ("public"."mensagem_chat_shopee" "m"
     JOIN "public"."view_mensagens_chat_ai" "v" ON (("v"."id" = "m"."id")));


ALTER VIEW "public"."view_mensagens_chat_ai_v2" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_movimentacoes_consolidadas" AS
 WITH "grupos" AS (
         SELECT "m"."correlation_id",
            COALESCE("m"."estagio", 'sem_estagio'::character varying) AS "estagio",
            "m"."item_demanda_id",
            "d"."id" AS "demanda_id_int",
            "d"."demanda_id" AS "demanda_codigo",
            "d"."descricao" AS "demanda_descricao",
            "min"("m"."data_movimentacao") AS "data_inicio",
            "max"("m"."data_movimentacao") AS "data_fim",
            "max"("m"."usuario_id") AS "usuario_id",
            "count"(*) AS "total_movimentos",
                CASE
                    WHEN "bool_or"((("m"."tipo_movimentacao")::"text" = 'PROD_ACAB'::"text")) THEN 'FINALIZACAO'::"text"
                    WHEN "bool_or"((("m"."tipo_movimentacao")::"text" = 'PROD_INT'::"text")) THEN 'JIT'::"text"
                    ELSE 'CONSUMO'::"text"
                END AS "tipo_bloco",
            ("array_agg"("m"."produto_id" ORDER BY
                CASE "m"."tipo_movimentacao"
                    WHEN 'PROD_ACAB'::"text" THEN 1
                    WHEN 'PROD_INT'::"text" THEN 2
                    ELSE 99
                END, "m"."data_movimentacao", "m"."id"))[1] AS "produto_foco_id",
            ("array_agg"("m"."produto_nome" ORDER BY
                CASE "m"."tipo_movimentacao"
                    WHEN 'PROD_ACAB'::"text" THEN 1
                    WHEN 'PROD_INT'::"text" THEN 2
                    ELSE 99
                END, "m"."data_movimentacao", "m"."id"))[1] AS "produto_foco_nome",
            COALESCE("sum"(
                CASE
                    WHEN (("m"."tipo_movimentacao")::"text" = 'PROD_ACAB'::"text") THEN "m"."quantidade"
                    ELSE (0)::numeric
                END), (0)::numeric) AS "quantidade_acabada",
            COALESCE("sum"(
                CASE
                    WHEN (("m"."tipo_movimentacao")::"text" = 'PROD_INT'::"text") THEN "m"."quantidade"
                    ELSE (0)::numeric
                END), (0)::numeric) AS "quantidade_intermediaria",
            "jsonb_agg"("jsonb_build_object"('id', "m"."id", 'produto_id', "m"."produto_id", 'produto_nome', "m"."produto_nome", 'tipo', "m"."tipo_movimentacao", 'quantidade', "m"."quantidade", 'saldo_antes', "m"."saldo_antes", 'saldo_depois', "m"."saldo_depois", 'deposito_id', "m"."deposito_id", 'motivo', "m"."motivo", 'data', "m"."data_movimentacao") ORDER BY "m"."data_movimentacao", "m"."id") AS "movimentos"
           FROM (("public"."movimentacoes_estoque" "m"
             LEFT JOIN "public"."itens_demanda" "i" ON (("i"."id" = "m"."item_demanda_id")))
             LEFT JOIN "public"."demandas_producao" "d" ON (("d"."id" = "i"."demanda_id")))
          WHERE ("m"."correlation_id" IS NOT NULL)
          GROUP BY "m"."correlation_id", "m"."estagio", "m"."item_demanda_id", "d"."id", "d"."demanda_id", "d"."descricao"
        )
 SELECT "correlation_id",
    "estagio",
    "item_demanda_id",
    "demanda_id_int",
    "demanda_codigo",
    "demanda_descricao",
    "data_inicio",
    "data_fim",
    "usuario_id",
    "total_movimentos",
    "tipo_bloco",
    "produto_foco_id",
    "produto_foco_nome",
        CASE "tipo_bloco"
            WHEN 'FINALIZACAO'::"text" THEN "quantidade_acabada"
            WHEN 'JIT'::"text" THEN "quantidade_intermediaria"
            ELSE (0)::numeric
        END AS "quantidade_principal",
        CASE "tipo_bloco"
            WHEN 'FINALIZACAO'::"text" THEN ((('Finalizacao de '::"text" || TRIM(BOTH '0'::"text" FROM TRIM(BOTH '.'::"text" FROM "to_char"("quantidade_acabada", 'FM999999990.0000'::"text")))) || ' x '::"text") || (COALESCE("produto_foco_nome", (('produto '::"text" || ("produto_foco_id")::"text"))::character varying))::"text")
            WHEN 'JIT'::"text" THEN ((('Producao JIT de '::"text" || TRIM(BOTH '0'::"text" FROM TRIM(BOTH '.'::"text" FROM "to_char"("quantidade_intermediaria", 'FM999999990.0000'::"text")))) || ' x '::"text") || (COALESCE("produto_foco_nome", (('produto '::"text" || ("produto_foco_id")::"text"))::character varying))::"text")
            ELSE ('Movimentacoes do estagio '::"text" || ("estagio")::"text")
        END AS "titulo",
    "movimentos"
   FROM "grupos"
  ORDER BY "data_inicio" DESC, "correlation_id", "estagio";


ALTER VIEW "public"."view_movimentacoes_consolidadas" OWNER TO "postgres";


COMMENT ON VIEW "public"."view_movimentacoes_consolidadas" IS 'Agrega movimentacoes_estoque por (correlation_id, estagio). Cada linha eh um bloco de negocio: FINALIZACAO (PROD_ACAB), JIT (PROD_INT) ou CONSUMO. Inclui titulo human-readable e o array de movimentos crus em "movimentos" (jsonb).';



CREATE OR REPLACE VIEW "public"."view_pedidos_personalizados_ai" WITH ("security_invoker"='true') AS
 WITH "base_orders" AS (
         SELECT "p"."id",
            "p"."numero_pedido",
            "p"."codigo_pedido_externo" AS "numero_loja",
            "p"."data_venda" AS "data_pedido",
            COALESCE("p"."informacoes_cliente", '{}'::"jsonb") AS "contato",
            COALESCE(NULLIF(TRIM(BOTH FROM "p"."cliente_nome"), ''::"text"), NULLIF(TRIM(BOTH FROM ("p"."informacoes_cliente" ->> 'nome'::"text")), ''::"text"), NULLIF(TRIM(BOTH FROM ("p"."informacoes_cliente" ->> 'name'::"text")), ''::"text"), NULLIF(TRIM(BOTH FROM "p"."buyer_username"), ''::"text"), ("p"."codigo_pedido_externo")::"text") AS "nome_cliente",
            "p"."buyer_username",
            "p"."message_to_seller" AS "shopee_message",
            "jsonb_strip_nulls"("jsonb_build_object"('username', "p"."buyer_username", 'marketplace_order_id', "p"."marketplace_order_id", 'contact_marketplace_id', "p"."contact_marketplace_id")) AS "informacoes_comprador",
            "p"."situacao_pedido_id",
            "pb"."bling_id"
           FROM (("public"."pedidos" "p"
             JOIN "public"."canais_venda" "cv" ON (("cv"."id" = "p"."canal_venda_id")))
             LEFT JOIN "public"."pedidos_bling" "pb" ON ((("pb"."numero_pedido")::"text" = ("p"."numero_pedido")::"text")))
          WHERE ((("cv"."slug")::"text" = 'shopee'::"text") AND ("p"."situacao_pedido_id" = 2) AND (EXISTS ( SELECT 1
                   FROM "public"."itens_pedido" "ip_1"
                  WHERE (("ip_1"."pedido_id" = "p"."id") AND ("ip_1"."personalizado" = true)))))
        ), "latest_logs" AS (
         SELECT DISTINCT ON ("l"."order_sn") "l"."order_sn",
            "l"."executed_at",
            "l"."status"
           FROM "public"."logs_execucao_ia" "l"
          ORDER BY "l"."order_sn", "l"."executed_at" DESC, "l"."id" DESC
        ), "chat_stats" AS (
         SELECT "bo_1"."id" AS "pedido_id",
            "max"("vm"."created_at") AS "last_chat_message_at",
            "max"("vm"."created_at") FILTER (WHERE ("vm"."from_user_name" = ("bo_1"."buyer_username")::"text")) AS "last_buyer_message_at"
           FROM ("base_orders" "bo_1"
             LEFT JOIN "public"."view_mensagens_chat_ai" "vm" ON ((("bo_1"."buyer_username" IS NOT NULL) AND (("bo_1"."buyer_username")::"text" <> ''::"text") AND (("vm"."from_user_name" = ("bo_1"."buyer_username")::"text") OR ("vm"."to_user_name" = ("bo_1"."buyer_username")::"text")))))
          GROUP BY "bo_1"."id"
        ), "item_personalizations" AS (
         SELECT "ip_1"."pedido_id",
            "jsonb_agg"("jsonb_build_object"('id', "ip_1"."id", 'codigo', "ip_1"."sku_externo", 'descricao', "ip_1"."descricao", 'quantidade', "ip_1"."quantidade", 'valor', "ip_1"."preco_unitario", 'unidade', 'UN', 'personalizado', "ip_1"."personalizado", 'produto', "jsonb_build_object"('id', "ip_1"."produto_id"), 'personalizations', COALESCE(( SELECT "jsonb_agg"("jsonb_build_object"('id', "pp"."id", 'item_pedido_id', "pp"."item_pedido_id", 'item_id', "pp"."item_id", 'item_description', "pp"."item_description", 'quantity_to_personalize', COALESCE((NULLIF(("pp"."detalhes_personalizacao" ->> 'quantity_to_personalize'::"text"), ''::"text"))::integer, (NULLIF(("pp"."metadata" ->> 'quantity_to_personalize'::"text"), ''::"text"))::integer, 1), 'customization_name', "pp"."customization_name", 'name_source_message_id', "pp"."name_source_message_id", 'customization_initial', "pp"."customization_initial", 'initial_source_message_id', COALESCE(("pp"."detalhes_personalizacao" ->> 'initial_source_message_id'::"text"), ("pp"."metadata" ->> 'initial_source_message_id'::"text")), 'status', "pp"."status", 'reasoning', "pp"."reasoning") ORDER BY "pp"."id") AS "jsonb_agg"
                   FROM "public"."personalizacoes_pedido" "pp"
                  WHERE (("pp"."item_pedido_id" = "ip_1"."id") OR (("pp"."item_pedido_id" IS NULL) AND ("pp"."shopee_order_sn" = (( SELECT "p2"."codigo_pedido_externo"
                           FROM "public"."pedidos" "p2"
                          WHERE ("p2"."id" = "ip_1"."pedido_id")))::"text") AND ("pp"."item_description" = ("ip_1"."descricao")::"text")))), '[]'::"jsonb")) ORDER BY "ip_1"."id") AS "itens"
           FROM "public"."itens_pedido" "ip_1"
          WHERE ("ip_1"."personalizado" = true)
          GROUP BY "ip_1"."pedido_id"
        )
 SELECT "bo"."id",
    "bo"."numero_pedido",
    "bo"."numero_loja",
    "bo"."data_pedido",
    "bo"."contato",
    "bo"."nome_cliente",
    "bo"."bling_id",
    true AS "personalizado",
    false AS "deletado",
    "bo"."informacoes_comprador",
    COALESCE("bo"."shopee_message", ''::"text") AS "shopee_message",
    "bo"."buyer_username",
    COALESCE(("cs"."last_chat_message_at" IS NOT NULL), false) AS "has_chat_messages",
    COALESCE(((NULLIF(TRIM(BOTH FROM COALESCE("bo"."shopee_message", ''::"text")), ''::"text") IS NOT NULL) OR ("cs"."last_buyer_message_at" IS NOT NULL)), false) AS "has_buyer_message",
    "cs"."last_chat_message_at",
    "cs"."last_buyer_message_at",
    "ll"."executed_at" AS "last_ai_executed_at",
    COALESCE("ll"."status", 'NOT_PROCESSED'::"text") AS "ai_status",
        CASE
            WHEN (NOT COALESCE(((NULLIF(TRIM(BOTH FROM COALESCE("bo"."shopee_message", ''::"text")), ''::"text") IS NOT NULL) OR ("cs"."last_buyer_message_at" IS NOT NULL)), false)) THEN false
            WHEN ("ll"."executed_at" IS NULL) THEN true
            WHEN (COALESCE("ll"."status", ''::"text") = ANY (ARRAY['error'::"text", 'db_error'::"text", 'no_response'::"text"])) THEN true
            WHEN (("cs"."last_buyer_message_at" IS NOT NULL) AND ("cs"."last_buyer_message_at" > "ll"."executed_at")) THEN true
            ELSE false
        END AS "needs_ai_processing",
    COALESCE("ip"."itens", '[]'::"jsonb") AS "itens"
   FROM ((("base_orders" "bo"
     LEFT JOIN "chat_stats" "cs" ON (("cs"."pedido_id" = "bo"."id")))
     LEFT JOIN "latest_logs" "ll" ON (("ll"."order_sn" = ("bo"."numero_loja")::"text")))
     LEFT JOIN "item_personalizations" "ip" ON (("ip"."pedido_id" = "bo"."id")));


ALTER VIEW "public"."view_pedidos_personalizados_ai" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_vendas_personalizadas" AS
 SELECT "pb"."id",
    "pb"."numero_pedido",
    "pb"."numero_loja",
    "pb"."data_pedido",
    "pb"."contato",
    "pb"."bling_id",
    "pb"."personalizado",
    "pb"."deletado",
    "ps"."informacoes_comprador",
    "ps"."mensagem" AS "shopee_message",
    COALESCE(("ps"."informacoes_comprador" ->> 'username'::"text"), ((("ps"."informacoes_comprador" #>> '{}'::"text"[]))::"jsonb" ->> 'username'::"text")) AS "buyer_username",
    (EXISTS ( SELECT 1
           FROM "public"."mensagem_chat_shopee" "mcs"
          WHERE (("mcs"."from_user_name" = COALESCE(("ps"."informacoes_comprador" ->> 'username'::"text"), ((("ps"."informacoes_comprador" #>> '{}'::"text"[]))::"jsonb" ->> 'username'::"text"))) OR ("mcs"."to_user_name" = COALESCE(("ps"."informacoes_comprador" ->> 'username'::"text"), ((("ps"."informacoes_comprador" #>> '{}'::"text"[]))::"jsonb" ->> 'username'::"text")))))) AS "has_chat_messages",
    "agg_itens"."itens_json" AS "itens"
   FROM (("public"."pedidos_bling" "pb"
     LEFT JOIN "public"."pedidos_shopee" "ps" ON (("pb"."numero_loja" = ("ps"."codigo_pedido")::"text")))
     LEFT JOIN LATERAL ( SELECT "jsonb_agg"("item_flat".*) AS "itens_json"
           FROM ( SELECT "it"."id",
                    "it"."codigo",
                    "it"."unidade",
                    "it"."quantidade",
                    "it"."valor",
                    "it"."descricao",
                    "it"."personalizado",
                    "it"."produto",
                    "agg_pers"."pers_json" AS "personalizations"
                   FROM ("public"."itens_pedido_bling" "it"
                     LEFT JOIN LATERAL ( SELECT "jsonb_agg"("p_json".*) AS "pers_json"
                           FROM ( SELECT "p"."id" AS "personalization_id",
                                    "p"."item_id",
                                    "p"."item_description",
                                    "p"."customization_name",
                                    "p"."customization_initial",
                                    "p"."name_source_message_id",
                                    "p"."status",
                                    "p"."reasoning"
                                   FROM "public"."personalizacoes_pedido" "p"
                                  WHERE (("p"."shopee_order_sn" = "pb"."numero_loja") AND ("p"."item_description" = ("it"."descricao")::"text"))) "p_json") "agg_pers" ON (true))
                  WHERE ("it"."pedido_bling_id" = "pb"."id")) "item_flat") "agg_itens" ON (true))
  WHERE ("pb"."personalizado" IS TRUE);


ALTER VIEW "public"."view_vendas_personalizadas" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_vendas_personalizadas_v3" WITH ("security_invoker"='true') AS
 SELECT "id",
    "numero_pedido",
    "numero_loja",
    "data_pedido",
    "contato",
    "nome_cliente",
    "bling_id",
    "personalizado",
    "deletado",
    "informacoes_comprador",
    "shopee_message",
    "buyer_username",
    "has_chat_messages",
    "has_buyer_message",
    "last_chat_message_at",
    "last_buyer_message_at",
    "last_ai_executed_at",
    "ai_status",
    "needs_ai_processing",
    "itens"
   FROM "public"."view_pedidos_personalizados_ai" "vpa";


ALTER VIEW "public"."view_vendas_personalizadas_v3" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."vinculos_bling" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "codigo_bling" character varying(255) NOT NULL,
    "configuracao_sync" "jsonb",
    "ultimo_sync" timestamp without time zone,
    "status_sync" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."vinculos_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."vinculos_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."vinculos_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."vinculos_bling_id_seq" OWNED BY "public"."vinculos_bling"."id";



CREATE TABLE IF NOT EXISTS "public"."vinculos_integracao_pedido" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "pedido_id" integer NOT NULL,
    "plataforma" character varying(50) NOT NULL,
    "id_na_plataforma" character varying(100) NOT NULL,
    "status_na_plataforma" character varying(50),
    "dados_brutos" "jsonb",
    "last_synced_at" timestamp with time zone DEFAULT "now"(),
    "created_at" timestamp with time zone DEFAULT "now"(),
    "integration_id" character varying(255)
);


ALTER TABLE "public"."vinculos_integracao_pedido" OWNER TO "postgres";


COMMENT ON COLUMN "public"."vinculos_integracao_pedido"."integration_id" IS 'ID da conta de integração específica para evitar colisão de IDs entre múltiplas contas.';



CREATE OR REPLACE VIEW "public"."vw_despacho_carimbo_inconsistente" AS
 SELECT "id" AS "pedido_id",
    "numero_pedido",
    "codigo_pedido_externo",
    "situacao_pedido_id",
    "despachado_em",
    (EXISTS ( SELECT 1
           FROM ("public"."demandas_pedidos" "dp"
             JOIN "public"."demandas_producao" "d" ON (("d"."id" = "dp"."demanda_id")))
          WHERE (("dp"."pedido_id" = "p"."id") AND (("d"."status")::"text" <> ALL ((ARRAY['RASCUNHO'::character varying, 'CANCELADO'::character varying, 'Cancelado'::character varying])::"text"[]))))) AS "em_demanda_publicada"
   FROM "public"."pedidos" "p"
  WHERE (("situacao_pedido_id" = ANY (ARRAY[2, 3, 4])) AND (("despachado_em" IS NOT NULL) <> (EXISTS ( SELECT 1
           FROM ("public"."demandas_pedidos" "dp"
             JOIN "public"."demandas_producao" "d" ON (("d"."id" = "dp"."demanda_id")))
          WHERE (("dp"."pedido_id" = "p"."id") AND (("d"."status")::"text" <> ALL ((ARRAY['RASCUNHO'::character varying, 'CANCELADO'::character varying, 'Cancelado'::character varying])::"text"[])))))));


ALTER VIEW "public"."vw_despacho_carimbo_inconsistente" OWNER TO "postgres";


COMMENT ON VIEW "public"."vw_despacho_carimbo_inconsistente" IS 'Pedido aberto cujo despachado_em nao bate com demandas_pedidos. Deve estar sempre vazia; linha aqui significa pedido escondido da torre ou contado duas vezes.';



CREATE OR REPLACE VIEW "public"."vw_pedidos_pendentes_despacho" WITH ("security_invoker"='true') AS
 SELECT "p"."id",
    "p"."uuid_pedido",
    "p"."numero_pedido",
    "p"."codigo_pedido_externo",
    "p"."origem",
    "p"."informacoes_cliente",
    "p"."situacao_pedido_id",
    "p"."total_pedido",
    "p"."moeda",
    "p"."data_venda",
    "p"."created_at",
    "p"."updated_at",
    "p"."cliente_nome",
    "p"."cliente_documento",
    "p"."canal_venda_id",
    "p"."cliente_telefone",
    "p"."cliente_email",
    "p"."is_flex",
    "p"."data_limite_envio",
    "p"."servico_logistico",
    "p"."payload_canonico",
    "p"."channel_snapshot",
    "p"."personalizado",
    "p"."buyer_username",
    "p"."marketplace_order_id",
    "p"."shipping_carrier",
    "p"."contact_marketplace_id",
    "p"."message_to_seller",
    "p"."pedido_bling_id",
    "p"."pedido_shopee_id",
    "p"."modalidade_logistica",
    "p"."marketplace_integration_id",
    "p"."status_original",
    "p"."pedido_mercadolivre_id",
    "p"."is_fulfillment",
    "p"."ingest_source",
    "p"."data_compra_marketplace",
    "p"."data_pagamento_marketplace",
    "p"."data_coleta",
    "p"."data_envio_marketplace",
    "p"."regra_logistica_integracao_id",
    "p"."marketplace_module_id",
    "p"."erp_integration_id",
    "p"."erp_store_id",
    "p"."erp_order_id",
    "p"."erp_order_number",
    "p"."marketplace_order_status",
    "p"."marketplace_payment_status",
    "p"."marketplace_shipping_status",
    "p"."marketplace_shipping_substatus",
    "p"."marketplace_lifecycle_stage",
    "p"."marketplace_status_updated_at",
    "p"."buyer_user_id",
    "p"."modalidade_logistica_id",
    "p"."modalidade_regra_id",
    "p"."metodo_envio_chave",
    "p"."metodo_envio_rotulo",
    "p"."modalidade_classificada_em",
    "p"."compromisso_logistico_em",
    "p"."despachado_em",
    "p"."pack_id",
    "m"."codigo" AS "modalidade_codigo",
    "m"."nome" AS "modalidade_nome",
    "m"."tipo_prazo" AS "modalidade_tipo_prazo",
    "m"."ordem_exibicao" AS "modalidade_ordem",
    "m"."entrega_rapida" AS "modalidade_entrega_rapida",
    COALESCE("ii"."instance_name", 'Origem nao resolvida'::character varying) AS "marketplace_nome"
   FROM (("public"."pedidos" "p"
     LEFT JOIN "public"."modalidades_logisticas" "m" ON (("m"."id" = "p"."modalidade_logistica_id")))
     LEFT JOIN "public"."installed_integrations" "ii" ON (("ii"."id" = "p"."marketplace_integration_id")))
  WHERE (("p"."despachado_em" IS NULL) AND ("p"."situacao_pedido_id" = 2) AND COALESCE("m"."entra_na_torre", (NOT COALESCE("p"."is_fulfillment", false))) AND (NOT (EXISTS ( SELECT 1
           FROM ("public"."demandas_pedidos" "dp"
             JOIN "public"."demandas_producao" "d" ON (("d"."id" = "dp"."demanda_id")))
          WHERE (("dp"."pedido_id" = "p"."id") AND (("d"."status")::"text" <> ALL ((ARRAY['RASCUNHO'::character varying, 'CANCELADO'::character varying, 'Cancelado'::character varying])::"text"[])))))));


ALTER VIEW "public"."vw_pedidos_pendentes_despacho" OWNER TO "postgres";


COMMENT ON VIEW "public"."vw_pedidos_pendentes_despacho" IS 'Definicao unica de "pedido que ainda precisa ser produzido": pago, sem NF emitida (situacao Em Andamento), nao despachado pela torre, fora de demanda publicada e fora de fulfillment. Toda contagem e todo escopo da torre saem daqui. Emitir a NF pelo Bling muda a situacao no marketplace e tira o pedido daqui — e o mesmo gesto que o retirava da planilha no fluxo legado.';



CREATE TABLE IF NOT EXISTS "public"."webhook_daily_stats" (
    "dia" "date" NOT NULL,
    "source" "text" DEFAULT '(sem source)'::"text" NOT NULL,
    "provider_topic" "text" DEFAULT '(sem topico)'::"text" NOT NULL,
    "last_status" "text" DEFAULT '(sem status)'::"text" NOT NULL,
    "total" bigint NOT NULL,
    "entregas" bigint,
    "atualizado_em" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."webhook_daily_stats" OWNER TO "postgres";


COMMENT ON TABLE "public"."webhook_daily_stats" IS 'Agregado diario permanente de webhook_events. A linha bruta vive 7 dias (janela de deduplicacao) e o payload, 1 dia.';



CREATE TABLE IF NOT EXISTS "public"."webhook_event_attempts" (
    "id" bigint NOT NULL,
    "webhook_event_id" bigint NOT NULL,
    "correlation_id" "uuid" NOT NULL,
    "attempt_number" integer NOT NULL,
    "status" "text" DEFAULT 'processing'::"text" NOT NULL,
    "queue_name" "text",
    "started_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "finished_at" timestamp with time zone,
    "error_type" "text",
    "error_message" "text",
    "result_summary" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."webhook_event_attempts" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."webhook_event_attempts_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."webhook_event_attempts_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."webhook_event_attempts_id_seq" OWNED BY "public"."webhook_event_attempts"."id";



CREATE TABLE IF NOT EXISTS "public"."webhook_events" (
    "id" bigint NOT NULL,
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "source" "text" DEFAULT 'bling'::"text" NOT NULL,
    "company_id" "text",
    "bling_id" bigint,
    "numero_loja" "text",
    "raw_payload" "jsonb" NOT NULL,
    "correlation_id" "uuid" NOT NULL,
    "pedido_id" bigint,
    "last_status" "text",
    "last_attempt_at" timestamp with time zone,
    "attempt_count" integer DEFAULT 0 NOT NULL,
    "provider_event_id" "text",
    "payload_hash" "text",
    "next_attempt_after" timestamp with time zone,
    "processing_started_at" timestamp with time zone,
    "processing_correlation_id" "uuid",
    "last_error_type" "text",
    "last_error_message" "text",
    "retry_expires_at" timestamp with time zone DEFAULT ("now"() + '7 days'::interval),
    "provider_topic" "text",
    "provider_resource" "text",
    "resolved_order_id" "text",
    "provider_updated_at" timestamp with time zone,
    "lifecycle_stage" "text",
    "dedupe_scope" "text" DEFAULT 'source'::"text" NOT NULL,
    "dedupe_key" "text" NOT NULL,
    "delivery_count" integer DEFAULT 1 NOT NULL,
    "last_received_at" timestamp with time zone,
    "raw_body" "text",
    "signature_status" "text",
    "signature_checked_at" timestamp with time zone,
    "signature_error" "text",
    "raw_archived_at" timestamp with time zone,
    "archive_object_key" "text",
    "provider_resource_type" "text",
    "provider_resource_id" "text",
    "resolution_status" "text",
    "resolved_order_ids" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "marketplace_integration_id" integer,
    CONSTRAINT "webhook_events_resolved_order_ids_array" CHECK (("jsonb_typeof"("resolved_order_ids") = 'array'::"text"))
);


ALTER TABLE "public"."webhook_events" OWNER TO "postgres";


COMMENT ON COLUMN "public"."webhook_events"."resolution_status" IS 'Typed adapter resolution outcome; does not imply domain processing success.';



COMMENT ON COLUMN "public"."webhook_events"."resolved_order_ids" IS 'Ordered unique provider order IDs resolved from the typed webhook resource.';



COMMENT ON COLUMN "public"."webhook_events"."marketplace_integration_id" IS 'Conta resolvida para este evento. Nulo enquanto a resolucao nao aconteceu (ou falhou) — o que por si so ja e um filtro util.';



CREATE SEQUENCE IF NOT EXISTS "public"."webhook_events_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."webhook_events_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."webhook_events_id_seq" OWNED BY "public"."webhook_events"."id";



CREATE TABLE IF NOT EXISTS "public"."webhook_logs" (
    "id" integer NOT NULL,
    "plataforma" character varying(50) NOT NULL,
    "instance_id" character varying(255),
    "evento" character varying(100),
    "payload" "jsonb" NOT NULL,
    "headers" "jsonb",
    "status" character varying(20) DEFAULT 'PENDENTE'::character varying,
    "mensagem_erro" "text",
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "processed_at" timestamp with time zone
);


ALTER TABLE "public"."webhook_logs" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."webhook_logs_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."webhook_logs_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."webhook_logs_id_seq" OWNED BY "public"."webhook_logs"."id";



ALTER TABLE ONLY "public"."agenda_recursos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."agenda_recursos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."alertas_demanda" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."alertas_demanda_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."archive_manifests" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."archive_manifests_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."canais_venda" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."canais_venda_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."canal_modalidade_mapeamento" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."canal_modalidade_mapeamento_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."categoria_bom_regras" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."categoria_bom_regras_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."categorias" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."categorias_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."componentes_ordem_producao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."componentes_ordem_producao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."configuracoes_aplicacao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."configuracoes_aplicacao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."consolidacoes_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."consolidacoes_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."conversoes_uom_produto" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."conversoes_uom_produto_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."demandas_item_origem" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."demandas_item_origem_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."demandas_overrides" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."demandas_overrides_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."demandas_pedidos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."demandas_pedidos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."demandas_producao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."demandas_producao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."depositos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."depositos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."estoque_atual" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."estoque_atual_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."eventos_auditoria" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."eventos_auditoria_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."execucoes_ai_item" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."execucoes_ai_item_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."feedback_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."feedback_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."ficha_tecnica" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."ficha_tecnica_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."fornecedor_insumos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."fornecedor_insumos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."fornecedores" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."fornecedores_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."installed_integrations" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."installed_integrations_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."integration_app_profiles" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."integration_app_profiles_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."integration_mapping_rules" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."integration_mapping_rules_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."integration_refresh_logs" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."integration_refresh_logs_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."integration_secret_values" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."integration_secret_values_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."integration_status_mappings" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."integration_status_mappings_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_demanda" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_demanda_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_ordem_compra" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_ordem_compra_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_pedido_bling" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_pedido_bling_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."janelas_despacho_execucoes" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."janelas_despacho_execucoes_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."logs_producao_diaria" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."logs_producao_diaria_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."manutencao_status_log" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."manutencao_status_log_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."metodos_envio_observados" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."metodos_envio_observados_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."modalidades_logisticas" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."modalidades_logisticas_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."movimentacoes_estoque" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."movimentacoes_estoque_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."notificacoes" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."notificacoes_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."oauth_authorization_sessions" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."oauth_authorization_sessions_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."ordens_compra" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."ordens_compra_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."ordens_producao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."ordens_producao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."order_identity_corrections" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."order_identity_corrections_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedido_ingest_log" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedido_ingest_log_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedido_integration_refs" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedido_integration_refs_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedido_snapshots" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedido_snapshots_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos_bling" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_bling_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos_mercadolivre" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_mercadolivre_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos_nao_classificados" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_nao_classificados_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos_shopee" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_shopee_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pending_marketplace_enrichments" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pending_marketplace_enrichments_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pending_order_reconciliations" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pending_order_reconciliations_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."permissoes_setor" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."permissoes_setor_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."personalizacoes_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."personalizacoes_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."plataformas" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."plataformas_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pontos_coleta" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pontos_coleta_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."produtos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."produtos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."produtos_externos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."produtos_externos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."recursos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."recursos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."recursos_produtivos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."recursos_produtivos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."regras_classificacao_modalidade" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."regras_classificacao_modalidade_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."regras_consolidacao_canal" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."regras_consolidacao_canal_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."regras_logisticas_canal" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."regras_logisticas_canal_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."regras_logisticas_integracao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."regras_logisticas_integracao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."regras_priorizacao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."regras_priorizacao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."setores" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."setores_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."sinalizacoes_demanda" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."sinalizacoes_demanda_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."situacoes_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."situacoes_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."sync_status_errors" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."sync_status_errors_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tags" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tags_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."templates_obs_canal" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."templates_obs_canal_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."transicoes_situacao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."transicoes_situacao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."unidades_medida" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."unidades_medida_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."usuarios" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."usuarios_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."vinculos_bling" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."vinculos_bling_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."webhook_event_attempts" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."webhook_event_attempts_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."webhook_events" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."webhook_events_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."webhook_logs" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."webhook_logs_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."agenda_recursos"
    ADD CONSTRAINT "agenda_recursos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."logs_execucao_ia"
    ADD CONSTRAINT "ai_execution_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."alertas_demanda"
    ADD CONSTRAINT "alertas_demanda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."archive_manifests"
    ADD CONSTRAINT "archive_manifests_dataset_object_key_key" UNIQUE ("dataset", "object_key");



ALTER TABLE ONLY "public"."archive_manifests"
    ADD CONSTRAINT "archive_manifests_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."cache_dashboard_pedidos"
    ADD CONSTRAINT "cache_dashboard_orders_pkey" PRIMARY KEY ("order_sn");



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."canal_modalidade_mapeamento"
    ADD CONSTRAINT "canal_modalidade_mapeamento_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."categoria_bom_regras"
    ADD CONSTRAINT "categoria_bom_regras_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."categorias"
    ADD CONSTRAINT "categorias_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."categorias"
    ADD CONSTRAINT "categorias_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."channel_connections"
    ADD CONSTRAINT "channel_connections_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."componentes_ordem_producao"
    ADD CONSTRAINT "componentes_ordem_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."conferencias_arquivo"
    ADD CONSTRAINT "conferencias_arquivo_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."configuracoes_aplicacao"
    ADD CONSTRAINT "configuracoes_aplicacao_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."configuracoes_aplicacao"
    ADD CONSTRAINT "configuracoes_aplicacao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."consolidacoes_pedido"
    ADD CONSTRAINT "consolidacoes_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."contas_bling"
    ADD CONSTRAINT "contas_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."contextos_producao"
    ADD CONSTRAINT "contextos_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demanda_alocacoes_estoque"
    ADD CONSTRAINT "demanda_alocacoes_estoque_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demanda_estoque_processado"
    ADD CONSTRAINT "demanda_estoque_processado_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demandas_item_origem"
    ADD CONSTRAINT "demandas_item_origem_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demandas_overrides"
    ADD CONSTRAINT "demandas_overrides_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demandas_pedidos"
    ADD CONSTRAINT "demandas_pedidos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_demanda_id_key" UNIQUE ("demanda_id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."depositos"
    ADD CONSTRAINT "depositos_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."depositos"
    ADD CONSTRAINT "depositos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."entity_correlation_mapping"
    ADD CONSTRAINT "entity_correlation_mapping_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."entrega_producao"
    ADD CONSTRAINT "entrega_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."erp_marketplace_links"
    ADD CONSTRAINT "erp_marketplace_links_erp_integration_id_erp_store_id_key" UNIQUE ("erp_integration_id", "erp_store_id");



ALTER TABLE ONLY "public"."erp_marketplace_links"
    ADD CONSTRAINT "erp_marketplace_links_erp_integration_id_marketplace_integr_key" UNIQUE ("erp_integration_id", "marketplace_integration_id");



ALTER TABLE ONLY "public"."erp_marketplace_links"
    ADD CONSTRAINT "erp_marketplace_links_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_produto_id_deposito_id_key" UNIQUE ("produto_id", "deposito_id");



ALTER TABLE ONLY "public"."eventos_auditoria"
    ADD CONSTRAINT "eventos_auditoria_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."eventos_pedido"
    ADD CONSTRAINT "eventos_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."eventos_producao_v2"
    ADD CONSTRAINT "eventos_producao_v2_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."execucoes_ai_batch"
    ADD CONSTRAINT "execucoes_ai_batch_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."execucoes_ai_item"
    ADD CONSTRAINT "execucoes_ai_item_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."feedback_pedido"
    ADD CONSTRAINT "feedback_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ficha_tecnica_classificacao_pendente"
    ADD CONSTRAINT "ficha_tecnica_classificacao_pendente_pkey" PRIMARY KEY ("ficha_tecnica_id");



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_produto_pai_id_componente_id_key" UNIQUE ("produto_pai_id", "componente_id");



ALTER TABLE ONLY "public"."fornecedor_insumos"
    ADD CONSTRAINT "fornecedor_insumos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."fornecedores"
    ADD CONSTRAINT "fornecedores_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ingest_daily_stats"
    ADD CONSTRAINT "ingest_daily_stats_pkey" PRIMARY KEY ("dia", "stage", "status");



ALTER TABLE ONLY "public"."installed_integrations"
    ADD CONSTRAINT "installed_integrations_module_instance_key" UNIQUE ("module_id", "instance_name");



ALTER TABLE ONLY "public"."installed_integrations"
    ADD CONSTRAINT "installed_integrations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integracao_canais_config"
    ADD CONSTRAINT "integracao_canais_config_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_account_routing"
    ADD CONSTRAINT "integration_account_routing_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_app_profiles"
    ADD CONSTRAINT "integration_app_profiles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_mapping_rules"
    ADD CONSTRAINT "integration_mapping_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_modules"
    ADD CONSTRAINT "integration_modules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_refresh_logs"
    ADD CONSTRAINT "integration_refresh_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_secret_values"
    ADD CONSTRAINT "integration_secret_values_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_status_mappings"
    ADD CONSTRAINT "integration_status_mappings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_ordem_compra"
    ADD CONSTRAINT "itens_ordem_compra_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_pedido_bling"
    ADD CONSTRAINT "itens_pedido_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_pedido"
    ADD CONSTRAINT "itens_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."janelas_despacho_execucoes"
    ADD CONSTRAINT "janelas_despacho_execucoes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_data_turno_equipe_id_key" UNIQUE ("data", "turno", "equipe_id");



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."manutencao_status_log"
    ADD CONSTRAINT "manutencao_status_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."marketplace_order_effects"
    ADD CONSTRAINT "marketplace_order_effects_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."marketplace_order_effects"
    ADD CONSTRAINT "marketplace_order_effects_transition_id_effect_type_key" UNIQUE ("transition_id", "effect_type");



ALTER TABLE ONLY "public"."marketplace_order_transitions"
    ADD CONSTRAINT "marketplace_order_transitions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."metodos_envio_observados"
    ADD CONSTRAINT "metodos_envio_observados_key" UNIQUE ("module_id", "campo_origem", "valor_normalizado");



ALTER TABLE ONLY "public"."metodos_envio_observados"
    ADD CONSTRAINT "metodos_envio_observados_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."modalidades_logisticas"
    ADD CONSTRAINT "modalidades_logisticas_module_codigo_key" UNIQUE ("module_id", "codigo");



ALTER TABLE ONLY "public"."modalidades_logisticas"
    ADD CONSTRAINT "modalidades_logisticas_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_idempotency_key_key" UNIQUE ("idempotency_key");



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notificacoes"
    ADD CONSTRAINT "notificacoes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."oauth_authorization_sessions"
    ADD CONSTRAINT "oauth_authorization_sessions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_numero_ordem_key" UNIQUE ("numero_ordem");



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_ordem_compra_id_key" UNIQUE ("ordem_compra_id");



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_numero_ordem_key" UNIQUE ("numero_ordem");



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_ordem_id_key" UNIQUE ("ordem_id");



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."order_identity_corrections"
    ADD CONSTRAINT "order_identity_corrections_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedido_ingest_log"
    ADD CONSTRAINT "pedido_ingest_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedido_integration_refs"
    ADD CONSTRAINT "pedido_integration_refs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedido_snapshots"
    ADD CONSTRAINT "pedido_snapshots_pedido_id_key" UNIQUE ("pedido_id");



ALTER TABLE ONLY "public"."pedido_snapshots"
    ADD CONSTRAINT "pedido_snapshots_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos_bling"
    ADD CONSTRAINT "pedidos_bling_bling_integration_bling_id_key" UNIQUE ("bling_integration_id", "bling_id");



ALTER TABLE ONLY "public"."pedidos_bling"
    ADD CONSTRAINT "pedidos_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos_mercadolivre"
    ADD CONSTRAINT "pedidos_mercadolivre_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos_nao_classificados"
    ADD CONSTRAINT "pedidos_nao_classificados_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_codigo_pedido_key" UNIQUE ("codigo_pedido");



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_id_pedido_shopee_key" UNIQUE ("id_pedido_shopee");



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_order_sn_key" UNIQUE ("order_sn");



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_uuid_pedido_key" UNIQUE ("uuid_pedido");



ALTER TABLE ONLY "public"."pending_marketplace_enrichments"
    ADD CONSTRAINT "pending_marketplace_enrichments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pending_order_reconciliations"
    ADD CONSTRAINT "pending_order_reconciliations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."perfis_fiscais"
    ADD CONSTRAINT "perfis_fiscais_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."perfis_fiscais"
    ADD CONSTRAINT "perfis_fiscais_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."permissoes_setor"
    ADD CONSTRAINT "permissoes_setor_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."personalizacoes_pedido"
    ADD CONSTRAINT "personalizacoes_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."plataformas"
    ADD CONSTRAINT "plataformas_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."plataformas"
    ADD CONSTRAINT "plataformas_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pontos_coleta"
    ADD CONSTRAINT "pontos_coleta_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."preferencias_ux_usuario"
    ADD CONSTRAINT "preferencias_ux_usuario_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."preferencias_ux_usuario"
    ADD CONSTRAINT "preferencias_ux_usuario_user_id_key" UNIQUE ("user_id");



ALTER TABLE ONLY "public"."previsao_consumo_demanda"
    ADD CONSTRAINT "previsao_consumo_demanda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produto_alias_conflitos"
    ADD CONSTRAINT "produto_alias_conflitos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produto_alias_conflitos"
    ADD CONSTRAINT "produto_alias_conflitos_produto_id_codigo_externo_produto_a_key" UNIQUE ("produto_id", "codigo_externo", "produto_alias_id");



ALTER TABLE ONLY "public"."produto_anuncios"
    ADD CONSTRAINT "produto_anuncios_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produto_eixo_opcao_componentes"
    ADD CONSTRAINT "produto_eixo_opcao_componentes_pkey" PRIMARY KEY ("opcao_id", "componente_produto_id");



ALTER TABLE ONLY "public"."produto_eixo_opcoes"
    ADD CONSTRAINT "produto_eixo_opcoes_eixo_id_codigo_key" UNIQUE ("eixo_id", "codigo");



ALTER TABLE ONLY "public"."produto_eixo_opcoes"
    ADD CONSTRAINT "produto_eixo_opcoes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produto_eixos"
    ADD CONSTRAINT "produto_eixos_codigo_key" UNIQUE ("codigo");



ALTER TABLE ONLY "public"."produto_eixos"
    ADD CONSTRAINT "produto_eixos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produto_pai_eixos"
    ADD CONSTRAINT "produto_pai_eixos_pkey" PRIMARY KEY ("produto_pai_id", "eixo_id");



ALTER TABLE ONLY "public"."produto_precos"
    ADD CONSTRAINT "produto_precos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produto_precos"
    ADD CONSTRAINT "produto_precos_produto_id_integration_id_tipo_vigencia_inic_key" UNIQUE ("produto_id", "integration_id", "tipo", "vigencia_inicio");



ALTER TABLE ONLY "public"."produto_sku_historico"
    ADD CONSTRAINT "produto_sku_historico_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produto_tags"
    ADD CONSTRAINT "produto_tags_pkey" PRIMARY KEY ("produto_id", "tag_id");



ALTER TABLE ONLY "public"."produto_variacao_backfill_revisao"
    ADD CONSTRAINT "produto_variacao_backfill_revisao_pkey" PRIMARY KEY ("produto_id");



ALTER TABLE ONLY "public"."produto_variacao_valores"
    ADD CONSTRAINT "produto_variacao_valores_pkey" PRIMARY KEY ("produto_id", "eixo_id");



ALTER TABLE ONLY "public"."produto_variacao_valores"
    ADD CONSTRAINT "produto_variacao_valores_produto_id_opcao_id_key" UNIQUE ("produto_id", "opcao_id");



ALTER TABLE ONLY "public"."produtos_externos"
    ADD CONSTRAINT "produtos_externos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_sku_key" UNIQUE ("sku");



ALTER TABLE ONLY "public"."recursos"
    ADD CONSTRAINT "recursos_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."recursos"
    ADD CONSTRAINT "recursos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."recursos_produtivos"
    ADD CONSTRAINT "recursos_produtivos_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."recursos_produtivos"
    ADD CONSTRAINT "recursos_produtivos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."regra_logistica_modalidades"
    ADD CONSTRAINT "regra_logistica_modalidades_pkey" PRIMARY KEY ("regra_id", "modalidade_id");



ALTER TABLE ONLY "public"."regras_classificacao_modalidade"
    ADD CONSTRAINT "regras_classificacao_modalidade_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."regras_consolidacao_canal"
    ADD CONSTRAINT "regras_consolidacao_canal_canal_venda_id_modalidade_key" UNIQUE ("canal_venda_id", "modalidade");



ALTER TABLE ONLY "public"."regras_consolidacao_canal"
    ADD CONSTRAINT "regras_consolidacao_canal_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."regras_logisticas_canal"
    ADD CONSTRAINT "regras_logisticas_canal_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."regras_logisticas_integracao"
    ADD CONSTRAINT "regras_logisticas_integracao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."regras_priorizacao"
    ADD CONSTRAINT "regras_priorizacao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."setores"
    ADD CONSTRAINT "setores_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."setores"
    ADD CONSTRAINT "setores_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sinalizacoes_demanda"
    ADD CONSTRAINT "sinalizacoes_demanda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."situacoes_pedido"
    ADD CONSTRAINT "situacoes_pedido_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."situacoes_pedido"
    ADD CONSTRAINT "situacoes_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sync_status_batches"
    ADD CONSTRAINT "sync_status_batches_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sync_status_errors"
    ADD CONSTRAINT "sync_status_errors_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."system_events_log"
    ADD CONSTRAINT "system_events_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tags"
    ADD CONSTRAINT "tags_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."tags"
    ADD CONSTRAINT "tags_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."task_daily_stats"
    ADD CONSTRAINT "task_daily_stats_pkey" PRIMARY KEY ("dia", "task_name", "task_type", "status");



ALTER TABLE ONLY "public"."task_execution_logs"
    ADD CONSTRAINT "task_execution_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."templates_obs_canal"
    ADD CONSTRAINT "templates_obs_canal_canal_venda_id_is_default_key" UNIQUE ("canal_venda_id", "is_default");



ALTER TABLE ONLY "public"."templates_obs_canal"
    ADD CONSTRAINT "templates_obs_canal_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_situacao_origem_id_situacao_destino_id_key" UNIQUE ("situacao_origem_id", "situacao_destino_id");



ALTER TABLE ONLY "public"."unidades_medida"
    ADD CONSTRAINT "unidades_medida_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."unidades_medida"
    ADD CONSTRAINT "unidades_medida_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."configuracoes_aplicacao"
    ADD CONSTRAINT "unique_config_per_entity" UNIQUE ("nome", "entidade_tipo", "entidade_id");



ALTER TABLE ONLY "public"."entity_correlation_mapping"
    ADD CONSTRAINT "unique_entity_correlation" UNIQUE ("entity_type", "entity_id", "correlation_id");



ALTER TABLE ONLY "public"."produtos_externos"
    ADD CONSTRAINT "unique_plataforma_codigo_externo" UNIQUE ("plataforma", "codigo_externo");



ALTER TABLE ONLY "public"."canal_modalidade_mapeamento"
    ADD CONSTRAINT "uq_canal_modalidade_padraes" UNIQUE ("canal_venda_id", "padrao_servico", "modalidade");



ALTER TABLE ONLY "public"."demandas_pedidos"
    ADD CONSTRAINT "uq_demandas_pedidos_demanda_pedido" UNIQUE ("demanda_id", "pedido_id");



ALTER TABLE ONLY "public"."pedidos_nao_classificados"
    ADD CONSTRAINT "uq_pedidos_nao_classificados_pedido" UNIQUE ("pedido_id");



ALTER TABLE ONLY "public"."usuarios"
    ADD CONSTRAINT "usuarios_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."usuarios"
    ADD CONSTRAINT "usuarios_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."grupo_mensagens_chat_shopee"
    ADD CONSTRAINT "v2_bundle_messages_pkey" PRIMARY KEY ("event_id", "msg_id");



ALTER TABLE ONLY "public"."mensagem_chat_shopee"
    ADD CONSTRAINT "v2_chat_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vinculos_bling"
    ADD CONSTRAINT "vinculos_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vinculos_bling"
    ADD CONSTRAINT "vinculos_bling_produto_id_codigo_bling_key" UNIQUE ("produto_id", "codigo_bling");



ALTER TABLE ONLY "public"."vinculos_integracao_pedido"
    ADD CONSTRAINT "vinculos_integracao_pedido_pedido_id_plataforma_key" UNIQUE ("pedido_id", "plataforma");



ALTER TABLE ONLY "public"."vinculos_integracao_pedido"
    ADD CONSTRAINT "vinculos_integracao_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."webhook_daily_stats"
    ADD CONSTRAINT "webhook_daily_stats_pkey" PRIMARY KEY ("dia", "source", "provider_topic", "last_status");



ALTER TABLE ONLY "public"."webhook_event_attempts"
    ADD CONSTRAINT "webhook_event_attempts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."webhook_events"
    ADD CONSTRAINT "webhook_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."webhook_logs"
    ADD CONSTRAINT "webhook_logs_pkey" PRIMARY KEY ("id");



CREATE INDEX "idx_ai_logs_order_sn" ON "public"."logs_execucao_ia" USING "btree" ("order_sn");



CREATE INDEX "idx_alertas_demanda_demanda_id" ON "public"."alertas_demanda" USING "btree" ("demanda_id");



CREATE INDEX "idx_alertas_demanda_requer_acao" ON "public"."alertas_demanda" USING "btree" ("requer_acao") WHERE ("requer_acao" = true);



CREATE INDEX "idx_alertas_demanda_resolvido" ON "public"."alertas_demanda" USING "btree" ("resolvido") WHERE ("resolvido" = false);



CREATE INDEX "idx_alertas_demanda_tipo" ON "public"."alertas_demanda" USING "btree" ("tipo_alerta");



CREATE INDEX "idx_canais_venda_ativo_horario" ON "public"."canais_venda" USING "btree" ("ativo", "horario_coleta") WHERE ("ativo" = true);



CREATE INDEX "idx_canais_venda_bling_loja_id" ON "public"."canais_venda" USING "btree" ("bling_loja_id_principal") WHERE ("bling_loja_id_principal" IS NOT NULL);



CREATE INDEX "idx_canais_venda_horario_coleta" ON "public"."canais_venda" USING "btree" ("horario_coleta") WHERE (("ativo" = true) AND ("horario_coleta" IS NOT NULL));



CREATE INDEX "idx_canais_venda_plataforma_id" ON "public"."canais_venda" USING "btree" ("plataforma_id") WHERE ("plataforma_id" IS NOT NULL);



CREATE INDEX "idx_canal_modalidade_canal" ON "public"."canal_modalidade_mapeamento" USING "btree" ("canal_venda_id") WHERE ("ativo" = true);



CREATE INDEX "idx_canal_modalidade_canal_modalidade" ON "public"."canal_modalidade_mapeamento" USING "btree" ("canal_venda_id", "modalidade") WHERE ("ativo" = true);



CREATE INDEX "idx_categoria_bom_regras_pai_id" ON "public"."categoria_bom_regras" USING "btree" ("categoria_pai_id");



CREATE INDEX "idx_channel_connections_aggregator_store_id" ON "public"."channel_connections" USING "btree" ("aggregator_store_id") WHERE (("aggregator_store_id" IS NOT NULL) AND ("is_active" = true));



CREATE INDEX "idx_channel_connections_bling" ON "public"."channel_connections" USING "btree" ("bling_integration_id") WHERE (("is_active" = true) AND ("bling_integration_id" IS NOT NULL));



COMMENT ON INDEX "public"."idx_channel_connections_bling" IS 'Lookup rápido: encontrar channel_connections por bling_integration_id';



CREATE INDEX "idx_channel_connections_bling_integration_id" ON "public"."channel_connections" USING "btree" ("bling_integration_id") WHERE ("is_active" = true);



CREATE INDEX "idx_channel_connections_channel_id" ON "public"."channel_connections" USING "btree" ("channel_id") WHERE ("is_active" = true);



CREATE INDEX "idx_channel_connections_ingest_origin_mode" ON "public"."channel_connections" USING "btree" ("ingest_origin_mode") WHERE ("is_active" = true);



CREATE INDEX "idx_channel_connections_integration_id" ON "public"."channel_connections" USING "btree" ("integration_id") WHERE ("is_active" = true);



CREATE INDEX "idx_channel_connections_marketplace" ON "public"."channel_connections" USING "btree" ("marketplace_integration_id") WHERE (("is_active" = true) AND ("marketplace_integration_id" IS NOT NULL));



COMMENT ON INDEX "public"."idx_channel_connections_marketplace" IS 'Lookup rápido: encontrar channel_connections por marketplace_integration_id';



CREATE INDEX "idx_channel_connections_marketplace_integration_id" ON "public"."channel_connections" USING "btree" ("marketplace_integration_id") WHERE ("is_active" = true);



CREATE INDEX "idx_channel_connections_marketplace_module" ON "public"."channel_connections" USING "btree" ("marketplace_module_id") WHERE ("is_active" = true);



CREATE INDEX "idx_channel_connections_store_to_integration" ON "public"."channel_connections" USING "btree" ("aggregator_store_id", "bling_integration_id") WHERE ("is_active" = true);



COMMENT ON INDEX "public"."idx_channel_connections_store_to_integration" IS 'Lookup rápido: dado aggregator_store_id (loja Bling), encontra bling_integration_id';



CREATE INDEX "idx_channel_connections_webhook_processing" ON "public"."channel_connections" USING "btree" ("bling_integration_id", "aggregator_store_id", "process_webhooks") WHERE (("is_active" = true) AND ("bling_integration_id" IS NOT NULL) AND ("aggregator_store_id" IS NOT NULL));



CREATE INDEX "idx_chat_created_at" ON "public"."mensagem_chat_shopee" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_chat_from_user" ON "public"."mensagem_chat_shopee" USING "btree" ("from_user_name");



CREATE INDEX "idx_chat_to_user" ON "public"."mensagem_chat_shopee" USING "btree" ("to_user_name");



CREATE INDEX "idx_config_categoria" ON "public"."configuracoes_aplicacao" USING "btree" ("categoria");



CREATE INDEX "idx_config_entidade" ON "public"."configuracoes_aplicacao" USING "btree" ("entidade_tipo", "entidade_id");



CREATE INDEX "idx_config_nome" ON "public"."configuracoes_aplicacao" USING "btree" ("nome");



CREATE INDEX "idx_consolidacoes_channel" ON "public"."consolidacoes_pedido" USING "btree" ("channel_id");



CREATE INDEX "idx_consolidacoes_created_at" ON "public"."consolidacoes_pedido" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_consolidacoes_platform" ON "public"."consolidacoes_pedido" USING "btree" ("platform");



CREATE INDEX "idx_consolidacoes_status" ON "public"."consolidacoes_pedido" USING "btree" ("status");



CREATE INDEX "idx_contextos_producao_canal_id" ON "public"."contextos_producao" USING "btree" ("canal_venda_id") WHERE ("is_active" = true);



CREATE INDEX "idx_contextos_producao_demanda_id" ON "public"."contextos_producao" USING "btree" ("demanda_id") WHERE ("is_active" = true);



CREATE INDEX "idx_contextos_producao_ordenacao" ON "public"."contextos_producao" USING "btree" ("canal_venda_id", "created_at" DESC) WHERE ("is_active" = true);



CREATE INDEX "idx_contextos_producao_pedido_id" ON "public"."contextos_producao" USING "btree" ("pedido_id") WHERE ("is_active" = true);



CREATE INDEX "idx_contextos_producao_tipo" ON "public"."contextos_producao" USING "btree" ("tipo");



CREATE INDEX "idx_demanda_alocacoes_correlation" ON "public"."demanda_alocacoes_estoque" USING "btree" ("correlation_id");



CREATE UNIQUE INDEX "idx_demanda_alocacoes_correlation_unique" ON "public"."demanda_alocacoes_estoque" USING "btree" ("correlation_id") WHERE (("status")::"text" <> 'CANCELADA'::"text");



CREATE INDEX "idx_demanda_alocacoes_demanda" ON "public"."demanda_alocacoes_estoque" USING "btree" ("demanda_id");



CREATE INDEX "idx_demanda_alocacoes_item" ON "public"."demanda_alocacoes_estoque" USING "btree" ("item_id");



CREATE INDEX "idx_demanda_alocacoes_item_produto" ON "public"."demanda_alocacoes_estoque" USING "btree" ("item_id", "produto_id") WHERE (("status")::"text" <> 'CANCELADA'::"text");



CREATE INDEX "idx_demanda_alocacoes_produto" ON "public"."demanda_alocacoes_estoque" USING "btree" ("produto_id");



CREATE INDEX "idx_demanda_alocacoes_status" ON "public"."demanda_alocacoes_estoque" USING "btree" ("status") WHERE (("status")::"text" = 'PENDENTE'::"text");



CREATE INDEX "idx_demanda_alocacoes_tipo" ON "public"."demanda_alocacoes_estoque" USING "btree" ("tipo_alocacao");



CREATE INDEX "idx_demandas_channel_snapshot_flex" ON "public"."demandas_producao" USING "btree" ((("channel_snapshot" ->> 'flex'::"text"))) WHERE (("channel_snapshot" IS NOT NULL) AND ("channel_snapshot" <> '{}'::"jsonb"));



CREATE INDEX "idx_demandas_classificacao" ON "public"."demandas_producao" USING "btree" ("classificacao_cliente");



CREATE INDEX "idx_demandas_contexto_logistico" ON "public"."demandas_producao" USING "btree" ("canal_venda_id", "modalidade_logistica", "is_flex", "fulfillment");



CREATE INDEX "idx_demandas_item_origem_demanda_item_id" ON "public"."demandas_item_origem" USING "btree" ("demanda_item_id");



CREATE INDEX "idx_demandas_item_origem_item" ON "public"."demandas_item_origem" USING "btree" ("demanda_item_id");



CREATE INDEX "idx_demandas_item_origem_pedido" ON "public"."demandas_item_origem" USING "btree" ("pedido_id");



CREATE INDEX "idx_demandas_item_origem_plataforma_pedido" ON "public"."demandas_item_origem" USING "btree" ("plataforma", "pedido_externo_id");



CREATE INDEX "idx_demandas_item_origem_sku_externo" ON "public"."demandas_item_origem" USING "btree" ("sku_externo");



CREATE INDEX "idx_demandas_modalidade" ON "public"."demandas_producao" USING "btree" ("modalidade_logistica");



CREATE INDEX "idx_demandas_origem" ON "public"."demandas_producao" USING "btree" ("origem_demanda") WHERE (("status")::"text" = 'RASCUNHO'::"text");



CREATE INDEX "idx_demandas_overrides_campo" ON "public"."demandas_overrides" USING "btree" ("campo");



CREATE INDEX "idx_demandas_overrides_contexto" ON "public"."demandas_overrides" USING "btree" ("contexto_origem");



CREATE INDEX "idx_demandas_overrides_demanda" ON "public"."demandas_overrides" USING "btree" ("demanda_id");



CREATE INDEX "idx_demandas_overrides_usuario" ON "public"."demandas_overrides" USING "btree" ("usuario_id");



CREATE INDEX "idx_demandas_priorizacao_ordenacao" ON "public"."demandas_producao" USING "btree" ("prioridade_manual" DESC, "prioridade" DESC, "data_entrega", "horario_coleta") WHERE (("status")::"text" = ANY ((ARRAY['AGUARDANDO'::character varying, 'EM_PRODUCAO'::character varying, 'COLETA_PARCIAL'::character varying])::"text"[]));



CREATE INDEX "idx_demandas_producao_data_coleta" ON "public"."demandas_producao" USING "btree" ("data_coleta");



CREATE INDEX "idx_demandas_producao_pedido_id" ON "public"."demandas_producao" USING "btree" ("pedido_id");



CREATE INDEX "idx_demandas_producao_status_normalizado" ON "public"."demandas_producao" USING "btree" ("status");



CREATE INDEX "idx_entity_correlation_entity" ON "public"."entity_correlation_mapping" USING "btree" ("entity_type", "entity_id");



CREATE INDEX "idx_entrega_producao_demanda_id" ON "public"."entrega_producao" USING "btree" ("demanda_id");



CREATE INDEX "idx_entrega_producao_item_id" ON "public"."entrega_producao" USING "btree" ("item_demanda_id");



CREATE INDEX "idx_erp_links_channel" ON "public"."erp_marketplace_links" USING "btree" ("channel_id") WHERE ("channel_id" IS NOT NULL);



CREATE INDEX "idx_erp_links_composite" ON "public"."erp_marketplace_links" USING "btree" ("erp_integration_id", "marketplace_integration_id");



CREATE INDEX "idx_erp_links_erp_id" ON "public"."erp_marketplace_links" USING "btree" ("erp_integration_id");



CREATE INDEX "idx_erp_links_marketplace_id" ON "public"."erp_marketplace_links" USING "btree" ("marketplace_integration_id");



CREATE INDEX "idx_erp_links_marketplace_module" ON "public"."erp_marketplace_links" USING "btree" ("marketplace_module_id");



CREATE INDEX "idx_erp_links_store_id" ON "public"."erp_marketplace_links" USING "btree" ("erp_store_id");



CREATE INDEX "idx_erp_marketplace_links_nfe" ON "public"."erp_marketplace_links" USING "btree" ("marketplace_integration_id", "nf_emission_mode") WHERE ("nf_emission_mode" <> 'disabled'::"text");



CREATE INDEX "idx_estoque_atual_deposito_produto" ON "public"."estoque_atual" USING "btree" ("deposito_id", "produto_id");



CREATE INDEX "idx_estoque_atual_produto_deposito" ON "public"."estoque_atual" USING "btree" ("produto_id", "deposito_id");



CREATE INDEX "idx_estoque_proc_demanda" ON "public"."demanda_estoque_processado" USING "btree" ("demanda_id");



CREATE INDEX "idx_estoque_proc_item_estagio" ON "public"."demanda_estoque_processado" USING "btree" ("item_id", "estagio");



CREATE INDEX "idx_estoque_proc_produto" ON "public"."demanda_estoque_processado" USING "btree" ("produto_id");



CREATE INDEX "idx_eventos_pedido_correlation_id" ON "public"."eventos_pedido" USING "btree" ("correlation_id");



CREATE INDEX "idx_eventos_pedido_id" ON "public"."eventos_pedido" USING "btree" ("pedido_id");



CREATE INDEX "idx_eventos_pedido_type" ON "public"."eventos_pedido" USING "btree" ("tipo_evento");



CREATE INDEX "idx_eventos_v2_item" ON "public"."eventos_producao_v2" USING "btree" ("item_demanda_id");



CREATE INDEX "idx_eventos_v2_processado" ON "public"."eventos_producao_v2" USING "btree" ("processado") WHERE ("processado" = false);



CREATE INDEX "idx_feedback_pedido_codigo" ON "public"."feedback_pedido" USING "btree" ("codigo_pedido");



CREATE INDEX "idx_ficha_tecnica_sku_comp" ON "public"."ficha_tecnica" USING "btree" ("sku_componente");



CREATE INDEX "idx_ficha_tecnica_sku_pai" ON "public"."ficha_tecnica" USING "btree" ("sku_produto_pai");



CREATE INDEX "idx_installed_integrations_is_default" ON "public"."installed_integrations" USING "btree" ("is_default") WHERE ("is_default" = true);



CREATE INDEX "idx_installed_integrations_is_placeholder" ON "public"."installed_integrations" USING "btree" ("is_placeholder") WHERE ("is_placeholder" = true);



CREATE INDEX "idx_installed_integrations_parent" ON "public"."installed_integrations" USING "btree" ("parent_integration_id");



CREATE INDEX "idx_installed_integrations_platform_slug" ON "public"."installed_integrations" USING "btree" ("platform_slug");



CREATE INDEX "idx_integracao_canais_bling_integration_id" ON "public"."integracao_canais_config" USING "btree" ("bling_integration_id") WHERE ("is_active" = true);



CREATE INDEX "idx_integracao_canais_bling_loja_id" ON "public"."integracao_canais_config" USING "btree" ("bling_loja_id") WHERE ("is_active" = true);



CREATE INDEX "idx_integracao_canais_canal_id" ON "public"."integracao_canais_config" USING "btree" ("canal_venda_id") WHERE ("is_active" = true);



CREATE INDEX "idx_integracao_canais_marketplace_integration_id" ON "public"."integracao_canais_config" USING "btree" ("marketplace_integration_id") WHERE ("is_active" = true);



CREATE INDEX "idx_integracao_canais_plataforma" ON "public"."integracao_canais_config" USING "btree" ("plataforma_nome") WHERE ("is_active" = true);



CREATE INDEX "idx_integration_mapping_resolution" ON "public"."integration_mapping_rules" USING "btree" ("module_id", "domain", "direction", "integration_id", "erp_marketplace_link_id", "priority" DESC) WHERE ("is_active" = true);



CREATE UNIQUE INDEX "idx_integration_modules_slug" ON "public"."integration_modules" USING "btree" ("slug") WHERE ("slug" IS NOT NULL);



CREATE INDEX "idx_integration_status_mappings_domain_status" ON "public"."integration_status_mappings" USING "btree" ("module_id", "status_domain", "external_status_id") WHERE ("is_active" = true);



CREATE INDEX "idx_integration_status_mappings_module_status" ON "public"."integration_status_mappings" USING "btree" ("module_id", "external_status_id") WHERE ("is_active" = true);



CREATE INDEX "idx_itens_demanda_status_processamento" ON "public"."itens_demanda" USING "btree" ("status_processamento");



CREATE INDEX "idx_itens_pedido_personalizado" ON "public"."itens_pedido" USING "btree" ("personalizado") WHERE ("personalizado" = true);



CREATE INDEX "idx_itens_pedido_personalizado_pedido" ON "public"."itens_pedido" USING "btree" ("pedido_id", "id") WHERE ("personalizado" = true);



CREATE INDEX "idx_ledger_demanda_estagio" ON "public"."demanda_estoque_processado" USING "btree" ("demanda_id", "estagio");



CREATE INDEX "idx_ledger_item_estagio_created" ON "public"."demanda_estoque_processado" USING "btree" ("item_id", "estagio", "created_at");



CREATE UNIQUE INDEX "idx_ledger_unique_correlation" ON "public"."demanda_estoque_processado" USING "btree" ("item_id", "estagio", "correlation_id", "produto_id", "tipo_movimentacao") WHERE ("correlation_id" IS NOT NULL);



COMMENT ON INDEX "public"."idx_ledger_unique_correlation" IS 'Idempotencia do ledger: 1 linha por (item, estagio, correlation, produto, tipo). A RPC reconciliar_item_estoque usa ON CONFLICT DO UPDATE para somar quantidades quando movimentos da mesma chave aparecem mais de uma vez (caso da explosao JIT que produz CONS_INT de estoque + CONS_INT espelhado do JIT do mesmo produto).';



CREATE INDEX "idx_logs_execucao_ia_order_sn_executed_at" ON "public"."logs_execucao_ia" USING "btree" ("order_sn", "executed_at" DESC);



CREATE INDEX "idx_logs_producao_diaria_data" ON "public"."logs_producao_diaria" USING "btree" ("data");



CREATE INDEX "idx_logs_producao_diaria_item_demanda_id" ON "public"."logs_producao_diaria" USING "btree" ("item_demanda_id");



CREATE INDEX "idx_mensagem_chat_shopee_conversation_ingest" ON "public"."mensagem_chat_shopee" USING "btree" ("installed_integration_id", "conversation_id", "created_at" DESC);



CREATE INDEX "idx_mensagem_chat_shopee_from_user_created_at" ON "public"."mensagem_chat_shopee" USING "btree" ("from_user_name", "created_at" DESC);



CREATE INDEX "idx_mensagem_chat_shopee_integration_from_id_created_at" ON "public"."mensagem_chat_shopee" USING "btree" ("installed_integration_id", "from_id", "created_at" DESC) WHERE ("from_id" IS NOT NULL);



CREATE INDEX "idx_mensagem_chat_shopee_received_at" ON "public"."mensagem_chat_shopee" USING "btree" ("received_at" DESC);



CREATE INDEX "idx_mensagem_chat_shopee_to_id_created_at" ON "public"."mensagem_chat_shopee" USING "btree" ("installed_integration_id", "to_id", "created_at" DESC) WHERE ("to_id" IS NOT NULL);



CREATE INDEX "idx_mensagem_chat_shopee_to_user_created_at" ON "public"."mensagem_chat_shopee" USING "btree" ("to_user_name", "created_at" DESC);



CREATE INDEX "idx_mensagem_chat_shopee_webhook_event_id" ON "public"."mensagem_chat_shopee" USING "btree" ("webhook_event_id") WHERE ("webhook_event_id" IS NOT NULL);



CREATE INDEX "idx_movimentacoes_correlation_id" ON "public"."movimentacoes_estoque" USING "btree" ("correlation_id");



CREATE INDEX "idx_movimentacoes_estoque_correlation_estagio" ON "public"."movimentacoes_estoque" USING "btree" ("correlation_id", "estagio") WHERE ("correlation_id" IS NOT NULL);



CREATE INDEX "idx_movimentacoes_estoque_item_demanda_id" ON "public"."movimentacoes_estoque" USING "btree" ("item_demanda_id");



CREATE INDEX "idx_movimentacoes_estoque_jit_item_demanda" ON "public"."movimentacoes_estoque" USING "btree" ("item_demanda_id", "produto_id", "is_jit");



CREATE INDEX "idx_movimentacoes_estoque_lote_id" ON "public"."movimentacoes_estoque" USING "btree" ("lote_id");



CREATE INDEX "idx_movimentacoes_origem_tipo" ON "public"."movimentacoes_estoque" USING "btree" ("origem_tipo");



CREATE INDEX "idx_movimentacoes_produto_demanda" ON "public"."movimentacoes_estoque" USING "btree" ("produto_nome", "demanda_nome");



CREATE INDEX "idx_pedido_ingest_log_created_at" ON "public"."pedido_ingest_log" USING "btree" ("created_at");



CREATE INDEX "idx_pedido_refs_pedido" ON "public"."pedido_integration_refs" USING "btree" ("pedido_id");



CREATE INDEX "idx_pedidos_bling_bling_id" ON "public"."pedidos_bling" USING "btree" ("bling_id");



CREATE INDEX "idx_pedidos_canal_status_data_venda" ON "public"."pedidos" USING "btree" ("canal_venda_id", "situacao_pedido_id", "data_venda" DESC);



CREATE INDEX "idx_pedidos_codigo_externo" ON "public"."pedidos" USING "btree" ("codigo_pedido_externo");



CREATE INDEX "idx_pedidos_data_coleta" ON "public"."pedidos" USING "btree" ("data_coleta");



CREATE INDEX "idx_pedidos_data_limite_envio" ON "public"."pedidos" USING "btree" ("data_limite_envio");



COMMENT ON INDEX "public"."idx_pedidos_data_limite_envio" IS 'Índice para filtro por período de data de envio';



CREATE INDEX "idx_pedidos_despacho_pendente" ON "public"."pedidos" USING "btree" ("marketplace_integration_id", "modalidade_logistica_id", "data_limite_envio") WHERE (("despachado_em" IS NULL) AND ("situacao_pedido_id" = ANY (ARRAY[2, 3, 4])));



CREATE INDEX "idx_pedidos_ingest_origin_mode" ON "public"."pedidos" USING "btree" ("marketplace_integration_id", "ingest_origin_mode") WHERE ("marketplace_integration_id" IS NOT NULL);



CREATE INDEX "idx_pedidos_is_flex" ON "public"."pedidos" USING "btree" ("is_flex") WHERE ("is_flex" = true);



COMMENT ON INDEX "public"."idx_pedidos_is_flex" IS 'Índice parcial para pedidos Flex (entrega rápida) - otimiza listagem de pedidos prioritários';



CREATE INDEX "idx_pedidos_is_flex_data_envio" ON "public"."pedidos" USING "btree" ("is_flex", "data_limite_envio") WHERE ("is_flex" = true);



COMMENT ON INDEX "public"."idx_pedidos_is_flex_data_envio" IS 'Índice composto para pedidos Flex ordenados por data de envio - usado na tela de consolidação';



CREATE INDEX "idx_pedidos_listing_marketplace_status_date" ON "public"."pedidos" USING "btree" ("marketplace_integration_id", "situacao_pedido_id", "data_venda" DESC);



CREATE INDEX "idx_pedidos_nao_classificados_canal" ON "public"."pedidos_nao_classificados" USING "btree" ("canal_venda_id") WHERE ("resolvido" = false);



CREATE INDEX "idx_pedidos_nao_classificados_pendentes" ON "public"."pedidos_nao_classificados" USING "btree" ("created_at" DESC) WHERE ("resolvido" = false);



CREATE INDEX "idx_pedidos_personalizado" ON "public"."pedidos" USING "btree" ("personalizado") WHERE ("personalizado" = true);



CREATE INDEX "idx_pedidos_personalizados_ativos" ON "public"."pedidos" USING "btree" ("marketplace_integration_id", "situacao_pedido_id", "data_venda" DESC, "id" DESC) WHERE (("situacao_pedido_id" = 2) AND ("personalizado" = true));



CREATE INDEX "idx_pedidos_status_flex_data" ON "public"."pedidos" USING "btree" ("situacao_pedido_id", "is_flex", "data_limite_envio");



COMMENT ON INDEX "public"."idx_pedidos_status_flex_data" IS 'Índice composto para filtros combinados de status, Flex e data de envio';



CREATE INDEX "idx_pedidos_status_shipping_deadline" ON "public"."pedidos" USING "btree" ("situacao_pedido_id", "data_limite_envio");



CREATE INDEX "idx_pending_direct_marketplace_reference" ON "public"."pending_order_reconciliations" USING "btree" ("erp_integration_id", "erp_store_id", "marketplace_module_id", "marketplace_order_id") WHERE (("status" = 'pending'::"text") AND ("reason" = 'direct_marketplace_reference'::"text"));



CREATE INDEX "idx_pending_marketplace_reconcile" ON "public"."pending_marketplace_enrichments" USING "btree" ("marketplace_module_id", "marketplace_order_id", "status");



CREATE INDEX "idx_pending_recon_proxima_tentativa" ON "public"."pending_order_reconciliations" USING "btree" ("status", "next_attempt_after") WHERE ("status" = 'pending'::"text");



CREATE INDEX "idx_personalizacoes_item_pedido_id" ON "public"."personalizacoes_pedido" USING "btree" ("item_pedido_id") WHERE ("item_pedido_id" IS NOT NULL);



CREATE INDEX "idx_personalizacoes_pedido_order_item" ON "public"."personalizacoes_pedido" USING "btree" ("shopee_order_sn", "item_description");



CREATE INDEX "idx_personalizacoes_shopee_order_sn" ON "public"."personalizacoes_pedido" USING "btree" ("shopee_order_sn");



CREATE INDEX "idx_personalizacoes_status" ON "public"."personalizacoes_pedido" USING "btree" ("status");



CREATE INDEX "idx_pontos_coleta_ativo" ON "public"."pontos_coleta" USING "btree" ("ativo");



CREATE INDEX "idx_previsao_demanda_id" ON "public"."previsao_consumo_demanda" USING "btree" ("demanda_id");



CREATE INDEX "idx_previsao_produto_id" ON "public"."previsao_consumo_demanda" USING "btree" ("produto_id");



CREATE INDEX "idx_produtos_atributos_status" ON "public"."produtos" USING "gin" ((("atributos" -> 'status'::"text")));



CREATE INDEX "idx_produtos_categoria_id" ON "public"."produtos" USING "btree" ("categoria_id");



CREATE INDEX "idx_produtos_estoque_minimo" ON "public"."produtos" USING "btree" ("estoque_minimo");



CREATE INDEX "idx_produtos_externos_codigo_externo" ON "public"."produtos_externos" USING "btree" ("codigo_externo");



CREATE INDEX "idx_produtos_externos_plataforma" ON "public"."produtos_externos" USING "btree" ("plataforma");



CREATE INDEX "idx_produtos_externos_produto_id" ON "public"."produtos_externos" USING "btree" ("produto_id");



CREATE INDEX "idx_produtos_formato" ON "public"."produtos" USING "btree" ("formato");



CREATE INDEX "idx_produtos_parent_id" ON "public"."produtos" USING "btree" ("parent_id");



CREATE INDEX "idx_produtos_personalizado" ON "public"."produtos" USING "btree" ("personalizado") WHERE ("personalizado" = true);



CREATE INDEX "idx_produtos_preco_custo" ON "public"."produtos" USING "btree" ("preco_custo");



CREATE INDEX "idx_produtos_preco_venda" ON "public"."produtos" USING "btree" ("preco_venda");



CREATE INDEX "idx_produtos_setor_responsavel" ON "public"."produtos" USING "btree" ("setor_responsavel_id");



CREATE INDEX "idx_produtos_sku_pai" ON "public"."produtos" USING "btree" ("sku_pai");



CREATE INDEX "idx_produtos_status" ON "public"."produtos" USING "btree" ("status");



CREATE INDEX "idx_produtos_tipo_material" ON "public"."produtos" USING "btree" ("tipo_material");



CREATE INDEX "idx_produtos_tipo_produto" ON "public"."produtos" USING "btree" ("tipo_produto");



CREATE INDEX "idx_produtos_unidade_medida_id" ON "public"."produtos" USING "btree" ("unidade_medida_id");



CREATE INDEX "idx_refresh_logs_created_at" ON "public"."integration_refresh_logs" USING "btree" ("created_at");



CREATE INDEX "idx_refresh_logs_integration" ON "public"."integration_refresh_logs" USING "btree" ("integration_id");



CREATE INDEX "idx_regras_canal_id" ON "public"."regras_logisticas_canal" USING "btree" ("canal_venda_id");



CREATE INDEX "idx_regras_consolidacao_canal" ON "public"."regras_consolidacao_canal" USING "btree" ("canal_venda_id") WHERE (("ativo" = true) AND ("canal_venda_id" IS NOT NULL));



CREATE INDEX "idx_regras_consolidacao_global" ON "public"."regras_consolidacao_canal" USING "btree" ("modalidade") WHERE (("ativo" = true) AND ("canal_venda_id" IS NULL));



CREATE INDEX "idx_regras_logisticas_canal_busca" ON "public"."regras_logisticas_canal" USING "btree" ("canal_venda_id", "modalidade", "prioridade_uso" DESC);



CREATE INDEX "idx_regras_logisticas_integracao_cutoff" ON "public"."regras_logisticas_integracao" USING "btree" ("marketplace_integration_id", "modalidade", "ativo", "horario_corte", "horario_coleta");



CREATE INDEX "idx_regras_logisticas_integracao_lookup" ON "public"."regras_logisticas_integracao" USING "btree" ("marketplace_integration_id", "modalidade", "ativo", "prioridade_uso" DESC);



CREATE INDEX "idx_regras_logisticas_integracao_ponto" ON "public"."regras_logisticas_integracao" USING "btree" ("ponto_coleta_id") WHERE ("ponto_coleta_id" IS NOT NULL);



CREATE INDEX "idx_regras_modalidade" ON "public"."regras_logisticas_canal" USING "btree" ("modalidade");



CREATE INDEX "idx_regras_priorizacao_ativas" ON "public"."regras_priorizacao" USING "btree" ("ativa", "prioridade_regra" DESC) WHERE ("ativa" = true);



CREATE INDEX "idx_routing_lookup" ON "public"."integration_account_routing" USING "btree" ("module", "function_name", "scope_type", "scope_id");



CREATE INDEX "idx_sinalizacoes_demanda_id" ON "public"."sinalizacoes_demanda" USING "btree" ("demanda_id") WHERE ("visivel" = true);



CREATE INDEX "idx_sinalizacoes_demanda_nao_lidas" ON "public"."sinalizacoes_demanda" USING "btree" ("demanda_id") WHERE (("visivel" = true) AND ("lido" = false));



CREATE INDEX "idx_sinalizacoes_demanda_tipo" ON "public"."sinalizacoes_demanda" USING "btree" ("tipo", "severidade") WHERE ("visivel" = true);



CREATE INDEX "idx_system_events_log_category" ON "public"."system_events_log" USING "btree" ("category");



CREATE INDEX "idx_system_events_log_created" ON "public"."system_events_log" USING "btree" ("created_at");



CREATE INDEX "idx_system_events_log_reference" ON "public"."system_events_log" USING "btree" ("reference_id");



CREATE INDEX "idx_system_events_log_severity" ON "public"."system_events_log" USING "btree" ("severity");



CREATE INDEX "idx_task_execution_logs_correlation_id" ON "public"."task_execution_logs" USING "btree" ("correlation_id");



CREATE INDEX "idx_task_execution_logs_created_at" ON "public"."task_execution_logs" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_task_execution_logs_status" ON "public"."task_execution_logs" USING "btree" ("status");



CREATE INDEX "idx_task_execution_logs_task_type" ON "public"."task_execution_logs" USING "btree" ("task_type");



CREATE INDEX "idx_templates_obs_canal_id" ON "public"."templates_obs_canal" USING "btree" ("canal_venda_id") WHERE ("is_default" = true);



CREATE INDEX "idx_templates_obs_canal_nome" ON "public"."templates_obs_canal" USING "btree" ("canal_venda_id", "nome");



CREATE INDEX "idx_vinculos_pedido_id_platform" ON "public"."vinculos_integracao_pedido" USING "btree" ("pedido_id", "plataforma") WHERE ("id_na_plataforma" IS NOT NULL);



CREATE INDEX "idx_vinculos_plataforma_id" ON "public"."vinculos_integracao_pedido" USING "btree" ("plataforma", "id_na_plataforma");



CREATE INDEX "idx_webhook_logs_created_at" ON "public"."webhook_logs" USING "btree" ("created_at");



CREATE INDEX "idx_webhook_logs_plataforma_status" ON "public"."webhook_logs" USING "btree" ("plataforma", "status");



CREATE UNIQUE INDEX "integracao_canais_config_bling_inst_loja_uq" ON "public"."integracao_canais_config" USING "btree" ("bling_integration_id", "bling_loja_id") WHERE (("bling_integration_id" IS NOT NULL) AND ("bling_loja_id" IS NOT NULL));



CREATE UNIQUE INDEX "integracao_canais_config_mp_inst_loja_uq" ON "public"."integracao_canais_config" USING "btree" ("marketplace_integration_id", "bling_loja_id") WHERE (("marketplace_integration_id" IS NOT NULL) AND ("bling_loja_id" IS NOT NULL));



CREATE INDEX "ix_channel_conn_aggregator" ON "public"."channel_connections" USING "btree" ("bling_integration_id", "aggregator_store_id") WHERE ("is_active" = true);



CREATE INDEX "ix_conferencias_arquivo_created_at" ON "public"."conferencias_arquivo" USING "btree" ("created_at" DESC);



CREATE INDEX "ix_demandas_pedidos_pedido" ON "public"."demandas_pedidos" USING "btree" ("pedido_id");



CREATE INDEX "ix_demandas_producao_status" ON "public"."demandas_producao" USING "btree" ("status");



CREATE INDEX "ix_ficha_classificacao_pendente" ON "public"."ficha_tecnica_classificacao_pendente" USING "btree" ("resolvido_em") WHERE ("resolvido_em" IS NULL);



CREATE INDEX "ix_ficha_tecnica_componente" ON "public"."ficha_tecnica" USING "btree" ("componente_id");



CREATE INDEX "ix_ficha_tecnica_pai" ON "public"."ficha_tecnica" USING "btree" ("produto_pai_id");



CREATE INDEX "ix_ficha_tecnica_sku_pai" ON "public"."ficha_tecnica" USING "btree" ("sku_produto_pai") WHERE ("sku_produto_pai" IS NOT NULL);



CREATE INDEX "ix_install_int_bling_loja_id" ON "public"."installed_integrations" USING "btree" ((("config" ->> 'bling_loja_id'::"text"))) WHERE ("is_active" = true);



CREATE INDEX "ix_install_int_cnpj" ON "public"."installed_integrations" USING "btree" ((("config" ->> 'cnpj'::"text"))) WHERE ("is_active" = true);



CREATE INDEX "ix_integration_status_mappings_lookup" ON "public"."integration_status_mappings" USING "btree" ("module_id", "status_domain", "external_status_id") WHERE "is_active";



CREATE INDEX "ix_itens_demanda_demanda" ON "public"."itens_demanda" USING "btree" ("demanda_id");



CREATE INDEX "ix_itens_pedido_pedido" ON "public"."itens_pedido" USING "btree" ("pedido_id");



CREATE INDEX "ix_itens_pedido_produto" ON "public"."itens_pedido" USING "btree" ("produto_id") WHERE ("produto_id" IS NOT NULL);



CREATE INDEX "ix_manutencao_status_log_lote" ON "public"."manutencao_status_log" USING "btree" ("lote");



CREATE INDEX "ix_marketplace_order_transitions_pedido_created" ON "public"."marketplace_order_transitions" USING "btree" ("pedido_id", "created_at" DESC);



CREATE INDEX "ix_metodos_envio_observados_novos" ON "public"."metodos_envio_observados" USING "btree" ("module_id", "ultima_ocorrencia_em" DESC) WHERE (("status")::"text" = 'NOVO'::"text");



CREATE INDEX "ix_mot_webhook_event_id" ON "public"."marketplace_order_transitions" USING "btree" ("webhook_event_id") WHERE ("webhook_event_id" IS NOT NULL);



CREATE INDEX "ix_pedido_ingest_log_integration" ON "public"."pedido_ingest_log" USING "btree" ("marketplace_integration_id", "created_at" DESC) WHERE ("marketplace_integration_id" IS NOT NULL);



CREATE INDEX "ix_pedidos_arvore_despacho" ON "public"."pedidos" USING "btree" ("marketplace_integration_id", "modalidade_logistica_id", "data_limite_envio") WHERE ("despachado_em" IS NULL);



CREATE INDEX "ix_pedidos_bling_integracao" ON "public"."pedidos_bling" USING "btree" ("integracao_instancia_id");



CREATE INDEX "ix_pedidos_bling_loja_id" ON "public"."pedidos_bling" USING "btree" ("loja_id");



CREATE INDEX "ix_pedidos_compromisso" ON "public"."pedidos" USING "btree" ("compromisso_logistico_em") WHERE ("despachado_em" IS NULL);



CREATE INDEX "ix_pedidos_erp_integration" ON "public"."pedidos" USING "btree" ("erp_integration_id");



CREATE INDEX "ix_pedidos_erp_integration_store" ON "public"."pedidos" USING "btree" ("erp_integration_id", "erp_store_id") WHERE (("erp_integration_id" IS NOT NULL) AND ("erp_store_id" IS NOT NULL));



CREATE INDEX "ix_pedidos_metodo_envio_chave" ON "public"."pedidos" USING "btree" ("metodo_envio_chave") WHERE ("metodo_envio_chave" IS NOT NULL);



CREATE INDEX "ix_pedidos_modalidade_nao_classificada" ON "public"."pedidos" USING "btree" ("marketplace_integration_id", "metodo_envio_chave") WHERE (("modalidade_logistica_id" IS NULL) AND ("despachado_em" IS NULL));



CREATE INDEX "ix_pedidos_numero_pedido" ON "public"."pedidos" USING "btree" ("numero_pedido");



CREATE INDEX "ix_pedidos_pack_id" ON "public"."pedidos" USING "btree" ("pack_id") WHERE ("pack_id" IS NOT NULL);



CREATE INDEX "ix_pedidos_pedido_bling_id" ON "public"."pedidos" USING "btree" ("pedido_bling_id") WHERE ("pedido_bling_id" IS NOT NULL);



CREATE INDEX "ix_pedidos_shopee_shop_id" ON "public"."pedidos_shopee" USING "btree" ("shop_id");



CREATE INDEX "ix_pending_reconciliations_pedido" ON "public"."pending_order_reconciliations" USING "btree" ("pedido_id") WHERE ("pedido_id" IS NOT NULL);



CREATE INDEX "ix_pil_bling_id" ON "public"."pedido_ingest_log" USING "btree" ("bling_id");



CREATE INDEX "ix_pil_correlation" ON "public"."pedido_ingest_log" USING "btree" ("correlation_id");



CREATE INDEX "ix_pil_created_at" ON "public"."pedido_ingest_log" USING "btree" ("created_at" DESC);



CREATE INDEX "ix_pil_numero_loja" ON "public"."pedido_ingest_log" USING "btree" ("numero_loja");



CREATE INDEX "ix_pil_pedido_id" ON "public"."pedido_ingest_log" USING "btree" ("pedido_id");



CREATE INDEX "ix_pil_stage" ON "public"."pedido_ingest_log" USING "btree" ("stage");



CREATE INDEX "ix_produto_alias_conflitos_pendente" ON "public"."produto_alias_conflitos" USING "btree" ("resolvido_em") WHERE ("resolvido_em" IS NULL);



CREATE INDEX "ix_produto_anuncios_externo" ON "public"."produto_anuncios" USING "btree" ("item_externo_id", "variacao_externa_id");



CREATE INDEX "ix_produto_anuncios_produto" ON "public"."produto_anuncios" USING "btree" ("produto_id");



CREATE INDEX "ix_produto_variacao_eixo" ON "public"."produto_variacao_valores" USING "btree" ("eixo_id", "opcao_id");



CREATE INDEX "ix_produtos_externos_codigo_upper" ON "public"."produtos_externos" USING "btree" ("upper"("btrim"(("codigo_externo")::"text")));



CREATE INDEX "ix_produtos_externos_produto" ON "public"."produtos_externos" USING "btree" ("produto_id");



CREATE INDEX "ix_produtos_sku_upper" ON "public"."produtos" USING "btree" ("upper"("btrim"(("sku")::"text")));



CREATE INDEX "ix_regra_logistica_modalidades_modalidade" ON "public"."regra_logistica_modalidades" USING "btree" ("modalidade_id");



CREATE INDEX "ix_regras_class_modalidade_lookup" ON "public"."regras_classificacao_modalidade" USING "btree" ("module_id", "prioridade", "id") WHERE "ativo";



CREATE INDEX "ix_webhook_event_attempts_event_id" ON "public"."webhook_event_attempts" USING "btree" ("webhook_event_id", "started_at" DESC);



CREATE INDEX "ix_webhook_events_backlog" ON "public"."webhook_events" USING "btree" ("last_status", "next_attempt_after", "received_at") WHERE ("last_status" = ANY (ARRAY['pending'::"text", 'accepted'::"text", 'pending_retry'::"text", 'processing'::"text"]));



CREATE INDEX "ix_webhook_events_bling_id" ON "public"."webhook_events" USING "btree" ("bling_id");



CREATE INDEX "ix_webhook_events_integration_status" ON "public"."webhook_events" USING "btree" ("marketplace_integration_id", "last_status", "received_at" DESC) WHERE ("marketplace_integration_id" IS NOT NULL);



CREATE INDEX "ix_webhook_events_last_attempt_at" ON "public"."webhook_events" USING "btree" ("last_attempt_at" DESC);



CREATE INDEX "ix_webhook_events_last_status" ON "public"."webhook_events" USING "btree" ("last_status");



CREATE INDEX "ix_webhook_events_numero_loja" ON "public"."webhook_events" USING "btree" ("numero_loja");



CREATE INDEX "ix_webhook_events_payload_hash" ON "public"."webhook_events" USING "btree" ("source", "payload_hash");



CREATE INDEX "ix_webhook_events_pedido_id" ON "public"."webhook_events" USING "btree" ("pedido_id");



CREATE INDEX "ix_webhook_events_provider_event_id" ON "public"."webhook_events" USING "btree" ("source", "provider_event_id") WHERE ("provider_event_id" IS NOT NULL);



CREATE INDEX "ix_webhook_events_received_at" ON "public"."webhook_events" USING "btree" ("received_at" DESC);



CREATE INDEX "ix_webhook_events_source" ON "public"."webhook_events" USING "btree" ("source");



CREATE INDEX "ix_webhook_events_source_order_received" ON "public"."webhook_events" USING "btree" ("source", "company_id", "numero_loja", "received_at");



CREATE INDEX "ix_webhook_events_source_retry_window" ON "public"."webhook_events" USING "btree" ("source", "last_status", "next_attempt_after", "received_at");



CREATE UNIQUE INDEX "unique_default_deposito" ON "public"."depositos" USING "btree" ("is_default") WHERE ("is_default" = true);



CREATE UNIQUE INDEX "uq_channel_connections_direct_integration_active" ON "public"."channel_connections" USING "btree" ("channel_id", "integration_id") WHERE (("aggregator_store_id" IS NULL) AND ("integration_id" IS NOT NULL) AND ("is_active" = true));



CREATE UNIQUE INDEX "uq_mensagem_chat_shopee_provider_message" ON "public"."mensagem_chat_shopee" USING "btree" ("installed_integration_id", "provider_message_id");



CREATE UNIQUE INDEX "uq_regra_logistica_conta_modalidade" ON "public"."regras_logisticas_integracao" USING "btree" ("marketplace_integration_id", "modalidade_id", "tipo_envio") WHERE ("ativo" AND ("modalidade_id" IS NOT NULL));



CREATE UNIQUE INDEX "uq_regras_logisticas_integracao_unique" ON "public"."regras_logisticas_integracao" USING "btree" ("marketplace_integration_id", "modalidade", "tipo_envio", "horario_limite", COALESCE("ponto_coleta_id", '-1'::integer)) WHERE ("ativo" = true);



CREATE UNIQUE INDEX "uq_webhook_events_dedupe" ON "public"."webhook_events" USING "btree" ("source", "dedupe_scope", "dedupe_key");



CREATE UNIQUE INDEX "uq_webhook_events_shopee_provider_event" ON "public"."webhook_events" USING "btree" ("source", "provider_event_id") WHERE (("source" = 'shopee'::"text") AND ("provider_resource" = 'chat_message'::"text") AND ("provider_event_id" IS NOT NULL));



CREATE UNIQUE INDEX "ux_channel_connections_active_bling_store" ON "public"."channel_connections" USING "btree" ("bling_integration_id", "aggregator_store_id") WHERE (("is_active" = true) AND ("bling_integration_id" IS NOT NULL) AND ("aggregator_store_id" IS NOT NULL));



CREATE UNIQUE INDEX "ux_erp_marketplace_links_operational_key" ON "public"."erp_marketplace_links" USING "btree" ("erp_integration_id", "marketplace_integration_id", "erp_store_id");



COMMENT ON INDEX "public"."ux_erp_marketplace_links_operational_key" IS 'Operational key for fulfillment routing: marketplace origin + ERP account + shop.id.';



CREATE UNIQUE INDEX "ux_integration_app_profiles_default_per_module" ON "public"."integration_app_profiles" USING "btree" ("module_id", "environment") WHERE ("is_default" = true);



CREATE UNIQUE INDEX "ux_integration_mapping_rule_scope" ON "public"."integration_mapping_rules" USING "btree" ("module_id", "integration_id", "erp_marketplace_link_id", "domain", "direction", "provider_value") NULLS NOT DISTINCT;



CREATE UNIQUE INDEX "ux_integration_status_mappings_domain" ON "public"."integration_status_mappings" USING "btree" ("module_id", COALESCE("integration_id", 0), "status_domain", "external_status_id");



CREATE UNIQUE INDEX "ux_integration_status_mappings_global" ON "public"."integration_status_mappings" USING "btree" ("module_id", "status_domain", "external_status_id") WHERE ("integration_id" IS NULL);



CREATE UNIQUE INDEX "ux_janelas_despacho_execucoes" ON "public"."janelas_despacho_execucoes" USING "btree" ("integration_id", "modalidade_id", "tipo", "janela_em");



CREATE UNIQUE INDEX "ux_marketplace_order_transition_provider_order" ON "public"."marketplace_order_transitions" USING "btree" ("module_id", "provider_event_id", "external_order_id") WHERE ("provider_event_id" IS NOT NULL);



CREATE UNIQUE INDEX "ux_oauth_authorization_sessions_state_hash" ON "public"."oauth_authorization_sessions" USING "btree" ("state_hash");



CREATE UNIQUE INDEX "ux_pedido_ref_integration_role" ON "public"."pedido_integration_refs" USING "btree" ("pedido_id", "integration_id", "role") NULLS NOT DISTINCT;



CREATE UNIQUE INDEX "ux_pedido_ref_provider_record" ON "public"."pedido_integration_refs" USING "btree" ("module_id", COALESCE("integration_id", 0), "external_order_id", "role") WHERE ("role" <> 'sales_origin'::"text");



CREATE UNIQUE INDEX "ux_pedido_ref_sales_origin" ON "public"."pedido_integration_refs" USING "btree" ("module_id", "external_order_id") WHERE ("role" = 'sales_origin'::"text");



CREATE UNIQUE INDEX "ux_pedidos_canonical_identity" ON "public"."pedidos" USING "btree" ("marketplace_module_id", "marketplace_order_id");



CREATE UNIQUE INDEX "ux_pedidos_meli_codigo_pedido" ON "public"."pedidos_mercadolivre" USING "btree" ("codigo_pedido");



CREATE UNIQUE INDEX "ux_pedidos_pedido_meli_id" ON "public"."pedidos" USING "btree" ("pedido_mercadolivre_id") WHERE ("pedido_mercadolivre_id" IS NOT NULL);



CREATE UNIQUE INDEX "ux_pedidos_pedido_shopee_id" ON "public"."pedidos" USING "btree" ("pedido_shopee_id") WHERE ("pedido_shopee_id" IS NOT NULL);



CREATE UNIQUE INDEX "ux_pending_marketplace_event" ON "public"."pending_marketplace_enrichments" USING "btree" ("marketplace_integration_id", "marketplace_order_id", "source_event_id") NULLS NOT DISTINCT;



CREATE UNIQUE INDEX "ux_pending_order_reconciliation_erp_order" ON "public"."pending_order_reconciliations" USING "btree" ("erp_integration_id", "erp_order_id", "status") WHERE ("erp_order_id" IS NOT NULL);



CREATE UNIQUE INDEX "ux_pending_order_reconciliation_order" ON "public"."pending_order_reconciliations" USING "btree" ("pedido_id") WHERE (("pedido_id" IS NOT NULL) AND ("status" = 'pending'::"text"));



CREATE UNIQUE INDEX "ux_produto_anuncios_chave_externa" ON "public"."produto_anuncios" USING "btree" ("integration_id", "item_externo_id", COALESCE("variacao_externa_id", ''::"text"));



CREATE UNIQUE INDEX "ux_produtos_externos_codigo" ON "public"."produtos_externos" USING "btree" (COALESCE("plataforma", '*'::character varying), "tipo", "upper"("btrim"(("codigo_externo")::"text")));



CREATE UNIQUE INDEX "ux_produtos_parent_combinacao" ON "public"."produtos" USING "btree" ("parent_id", "combinacao_chave") WHERE (("parent_id" IS NOT NULL) AND ("combinacao_chave" IS NOT NULL));



CREATE UNIQUE INDEX "ux_produtos_sku_normalizado" ON "public"."produtos" USING "btree" ("upper"("btrim"("regexp_replace"(("sku")::"text", '[[:space:]]+'::"text", ' '::"text", 'g'::"text"))));



COMMENT ON INDEX "public"."ux_produtos_sku_normalizado" IS 'SKU unico no espaco normalizado: colapsa qualquer whitespace (inclusive tabulacao) e so entao apara as pontas. Impede cadastrar ou editar um SKU para cima de outro que so difere por espaco, tabulacao ou caixa.';



CREATE UNIQUE INDEX "ux_public_integration_secret_values_owner_kind" ON "public"."integration_secret_values" USING "btree" ("owner_type", "owner_id", "secret_kind");



CREATE UNIQUE INDEX "ux_vinculos_integracao_scoped_external_id" ON "public"."vinculos_integracao_pedido" USING "btree" ("integration_id", "plataforma", "id_na_plataforma");



CREATE OR REPLACE TRIGGER "demandas_pedidos_sincroniza_carimbo_del" AFTER DELETE ON "public"."demandas_pedidos" REFERENCING OLD TABLE AS "antigos" FOR EACH STATEMENT EXECUTE FUNCTION "public"."trg_demandas_pedidos_sincroniza_carimbo"();



CREATE OR REPLACE TRIGGER "demandas_pedidos_sincroniza_carimbo_ins" AFTER INSERT ON "public"."demandas_pedidos" REFERENCING NEW TABLE AS "novos" FOR EACH STATEMENT EXECUTE FUNCTION "public"."trg_demandas_pedidos_sincroniza_carimbo"();



CREATE OR REPLACE TRIGGER "demandas_producao_sincroniza_carimbo" AFTER UPDATE ON "public"."demandas_producao" REFERENCING OLD TABLE AS "antigos" NEW TABLE AS "novos" FOR EACH STATEMENT EXECUTE FUNCTION "public"."trg_demandas_producao_sincroniza_carimbo"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."configuracoes_aplicacao" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."demandas_producao" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "tg_modalidades_logisticas_touch" BEFORE UPDATE ON "public"."modalidades_logisticas" FOR EACH ROW EXECUTE FUNCTION "public"."tg_touch_updated_at"();



CREATE OR REPLACE TRIGGER "tg_pedido_classifica_modalidade" AFTER INSERT OR UPDATE OF "metodo_envio_chave", "metodo_envio_rotulo", "modalidade_logistica" ON "public"."pedidos" FOR EACH ROW EXECUTE FUNCTION "public"."tg_pedido_classifica_modalidade"();



CREATE OR REPLACE TRIGGER "tg_pedidos_sync_is_flex" BEFORE INSERT OR UPDATE OF "modalidade_logistica_id" ON "public"."pedidos" FOR EACH ROW EXECUTE FUNCTION "public"."tg_pedidos_sync_is_flex"();



CREATE OR REPLACE TRIGGER "tg_regra_logistica_sync_modalidade" BEFORE INSERT OR UPDATE ON "public"."regras_logisticas_integracao" FOR EACH ROW EXECUTE FUNCTION "public"."tg_regra_logistica_sync_modalidade"();



CREATE OR REPLACE TRIGGER "tg_regras_class_modalidade_touch" BEFORE UPDATE ON "public"."regras_classificacao_modalidade" FOR EACH ROW EXECUTE FUNCTION "public"."tg_touch_updated_at"();



CREATE OR REPLACE TRIGGER "tg_snapshot_classifica_modalidade" AFTER INSERT OR UPDATE OF "platform_fields" ON "public"."pedido_snapshots" FOR EACH ROW EXECUTE FUNCTION "public"."tg_snapshot_classifica_modalidade"();



CREATE OR REPLACE TRIGGER "trg_atualizar_chave_combinacao" AFTER INSERT OR DELETE OR UPDATE ON "public"."produto_variacao_valores" FOR EACH ROW EXECUTE FUNCTION "public"."atualizar_chave_combinacao_variacao"();



CREATE OR REPLACE TRIGGER "trg_atualizar_requer_revisao" BEFORE INSERT OR UPDATE OF "pedidos_apos_edicao_qtd" ON "public"."demandas_producao" FOR EACH ROW EXECUTE FUNCTION "public"."fn_atualizar_requer_revisao"();



CREATE OR REPLACE TRIGGER "trg_auditoria_produto_anuncios" AFTER INSERT OR DELETE OR UPDATE ON "public"."produto_anuncios" FOR EACH ROW EXECUTE FUNCTION "public"."auditar_cadastro_produto"();



CREATE OR REPLACE TRIGGER "trg_auditoria_produto_precos" AFTER INSERT OR DELETE OR UPDATE ON "public"."produto_precos" FOR EACH ROW EXECUTE FUNCTION "public"."auditar_cadastro_produto"();



CREATE OR REPLACE TRIGGER "trg_auditoria_produtos" AFTER INSERT OR DELETE OR UPDATE ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."auditar_cadastro_produto"();



CREATE OR REPLACE TRIGGER "trg_cascade_tipo_pai_para_variacoes" AFTER UPDATE OF "tipo_produto", "tipo_material" ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."cascade_tipo_pai_para_variacoes"();



CREATE OR REPLACE TRIGGER "trg_enforce_marketplace_order_authority" BEFORE UPDATE ON "public"."pedidos" FOR EACH ROW EXECUTE FUNCTION "public"."enforce_marketplace_order_authority"();



CREATE OR REPLACE TRIGGER "trg_item_pedido_enriquece" AFTER INSERT ON "public"."itens_pedido" FOR EACH ROW WHEN (("new"."titulo_anuncio" IS NULL)) EXECUTE FUNCTION "public"."tg_item_pedido_enriquece"();



CREATE OR REPLACE TRIGGER "trg_registrar_alteracao_sku" BEFORE UPDATE OF "sku" ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."registrar_alteracao_sku"();



CREATE OR REPLACE TRIGGER "trg_regra_sincroniza_modalidade" AFTER INSERT OR UPDATE OF "modalidade_id" ON "public"."regras_logisticas_integracao" FOR EACH ROW EXECUTE FUNCTION "public"."tg_regra_sincroniza_modalidade_principal"();



CREATE OR REPLACE TRIGGER "trg_sincronizar_tipo_produto" BEFORE INSERT OR UPDATE ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."sincronizar_tipo_produto"();



CREATE OR REPLACE TRIGGER "trg_snapshot_channel_before_demand_insert" BEFORE INSERT ON "public"."demandas_producao" FOR EACH ROW WHEN (("new"."canal_venda_id" IS NOT NULL)) EXECUTE FUNCTION "public"."fn_snapshot_channel_on_insert"();



COMMENT ON TRIGGER "trg_snapshot_channel_before_demand_insert" ON "public"."demandas_producao" IS 'Captura snapshot do canal no momento da criação da demanda.';



CREATE OR REPLACE TRIGGER "trg_snapshot_channel_before_order_insert" BEFORE INSERT ON "public"."pedidos" FOR EACH ROW WHEN (("new"."canal_venda_id" IS NOT NULL)) EXECUTE FUNCTION "public"."fn_snapshot_channel_on_insert"();



COMMENT ON TRIGGER "trg_snapshot_channel_before_order_insert" ON "public"."pedidos" IS 'Captura snapshot do canal no momento da criação do pedido.
   Sincroniza is_flex denormalizado com o snapshot.';



CREATE OR REPLACE TRIGGER "trg_snapshot_enriquece_itens" AFTER INSERT OR UPDATE OF "items" ON "public"."pedido_snapshots" FOR EACH ROW EXECUTE FUNCTION "public"."tg_snapshot_enriquece_itens"();



CREATE OR REPLACE TRIGGER "trg_sync_canonical_order_compat_fields" BEFORE INSERT OR UPDATE ON "public"."pedidos" FOR EACH ROW EXECUTE FUNCTION "public"."sync_canonical_order_compat_fields"();



CREATE OR REPLACE TRIGGER "trg_sync_marketplace_snapshot_items" AFTER INSERT OR UPDATE OF "items", "identity" ON "public"."pedido_snapshots" FOR EACH ROW EXECUTE FUNCTION "public"."sync_marketplace_snapshot_items"();



CREATE OR REPLACE TRIGGER "trg_update_alertas_demanda" BEFORE UPDATE ON "public"."alertas_demanda" FOR EACH ROW EXECUTE FUNCTION "public"."update_alertas_demanda_updated_at"();



CREATE OR REPLACE TRIGGER "trg_validar_componente_ficha_tecnica" BEFORE INSERT OR UPDATE OF "componente_id" ON "public"."ficha_tecnica" FOR EACH ROW EXECUTE FUNCTION "public"."validar_componente_ficha_tecnica"();



CREATE OR REPLACE TRIGGER "trg_validar_componente_kit" BEFORE INSERT OR UPDATE OF "produto_pai_id", "componente_id" ON "public"."ficha_tecnica" FOR EACH ROW EXECUTE FUNCTION "public"."validar_componente_kit"();



CREATE OR REPLACE TRIGGER "trg_validar_preco_produto" BEFORE INSERT OR UPDATE ON "public"."produto_precos" FOR EACH ROW EXECUTE FUNCTION "public"."validar_preco_produto"();



CREATE OR REPLACE TRIGGER "trg_validar_tipo_produto_variacao" BEFORE INSERT OR UPDATE OF "tipo_produto", "tipo_material", "parent_id" ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."validar_tipo_produto_variacao"();



CREATE OR REPLACE TRIGGER "trigger_update_consolidacoes_updated_at" BEFORE UPDATE ON "public"."consolidacoes_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_consolidacoes_updated_at"();



CREATE OR REPLACE TRIGGER "update_agenda_recursos_updated_at" BEFORE UPDATE ON "public"."agenda_recursos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_canais_venda_updated_at" BEFORE UPDATE ON "public"."canais_venda" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_canal_modalidade_mapeamento_updated_at" BEFORE UPDATE ON "public"."canal_modalidade_mapeamento" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_categorias_updated_at" BEFORE UPDATE ON "public"."categorias" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_channel_connections_updated_at" BEFORE UPDATE ON "public"."channel_connections" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_componentes_ordem_producao_updated_at" BEFORE UPDATE ON "public"."componentes_ordem_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_contas_bling_updated_at" BEFORE UPDATE ON "public"."contas_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_contextos_producao_updated_at" BEFORE UPDATE ON "public"."contextos_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_conversoes_uom_produto_updated_at" BEFORE UPDATE ON "public"."conversoes_uom_produto" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_demanda_estoque_processado_modtime" BEFORE UPDATE ON "public"."demanda_estoque_processado" FOR EACH ROW EXECUTE FUNCTION "public"."update_modified_column"();



CREATE OR REPLACE TRIGGER "update_demandas_overrides_updated_at" BEFORE UPDATE ON "public"."demandas_overrides" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_depositos_updated_at" BEFORE UPDATE ON "public"."depositos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_entrega_producao_updated_at" BEFORE UPDATE ON "public"."entrega_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_erp_marketplace_links_updated_at" BEFORE UPDATE ON "public"."erp_marketplace_links" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_estoque_atual_updated_at" BEFORE UPDATE ON "public"."estoque_atual" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_eventos_auditoria_updated_at" BEFORE UPDATE ON "public"."eventos_auditoria" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_feedback_pedido_updated_at" BEFORE UPDATE ON "public"."feedback_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ficha_tecnica_updated_at" BEFORE UPDATE ON "public"."ficha_tecnica" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_fornecedores_updated_at" BEFORE UPDATE ON "public"."fornecedores" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_integracao_canais_config_updated_at" BEFORE UPDATE ON "public"."integracao_canais_config" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_demanda_updated_at" BEFORE UPDATE ON "public"."itens_demanda" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_ordem_compra_updated_at" BEFORE UPDATE ON "public"."itens_ordem_compra" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_pedido_bling_updated_at" BEFORE UPDATE ON "public"."itens_pedido_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_pedido_updated_at" BEFORE UPDATE ON "public"."itens_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_logs_producao_diaria_updated_at" BEFORE UPDATE ON "public"."logs_producao_diaria" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_notificacoes_updated_at" BEFORE UPDATE ON "public"."notificacoes" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ordens_compra_updated_at" BEFORE UPDATE ON "public"."ordens_compra" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ordens_producao_updated_at" BEFORE UPDATE ON "public"."ordens_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pedidos_bling_updated_at" BEFORE UPDATE ON "public"."pedidos_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pedidos_shopee_updated_at" BEFORE UPDATE ON "public"."pedidos_shopee" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pedidos_updated_at" BEFORE UPDATE ON "public"."pedidos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_permissoes_setor_updated_at" BEFORE UPDATE ON "public"."permissoes_setor" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_personalizacoes_pedido_updated_at" BEFORE UPDATE ON "public"."personalizacoes_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_plataformas_updated_at" BEFORE UPDATE ON "public"."plataformas" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pontos_coleta_updated_at" BEFORE UPDATE ON "public"."pontos_coleta" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_preferencias_ux_usuario_updated_at" BEFORE UPDATE ON "public"."preferencias_ux_usuario" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_produtos_externos_updated_at" BEFORE UPDATE ON "public"."produtos_externos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_recursos_produtivos_updated_at" BEFORE UPDATE ON "public"."recursos_produtivos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_regras_consolidacao_canal_updated_at" BEFORE UPDATE ON "public"."regras_consolidacao_canal" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_regras_logisticas_integracao_updated_at" BEFORE UPDATE ON "public"."regras_logisticas_integracao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_regras_priorizacao_updated_at" BEFORE UPDATE ON "public"."regras_priorizacao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_setores_updated_at" BEFORE UPDATE ON "public"."setores" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_situacoes_pedido_updated_at" BEFORE UPDATE ON "public"."situacoes_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_tags_updated_at" BEFORE UPDATE ON "public"."tags" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_templates_obs_canal_updated_at" BEFORE UPDATE ON "public"."templates_obs_canal" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_transicoes_situacao_updated_at" BEFORE UPDATE ON "public"."transicoes_situacao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_unidades_medida_updated_at" BEFORE UPDATE ON "public"."unidades_medida" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_usuarios_updated_at" BEFORE UPDATE ON "public"."usuarios" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_vinculos_bling_updated_at" BEFORE UPDATE ON "public"."vinculos_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



ALTER TABLE ONLY "public"."agenda_recursos"
    ADD CONSTRAINT "agenda_recursos_recurso_id_fkey" FOREIGN KEY ("recurso_id") REFERENCES "public"."recursos_produtivos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."alertas_demanda"
    ADD CONSTRAINT "alertas_demanda_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."alertas_demanda"
    ADD CONSTRAINT "alertas_demanda_resolvido_por_fkey" FOREIGN KEY ("resolvido_por") REFERENCES "public"."usuarios"("id");



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_conta_bling_id_fkey" FOREIGN KEY ("conta_bling_id") REFERENCES "public"."contas_bling"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_integration_id_principal_fkey" FOREIGN KEY ("integration_id_principal") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_plataforma_id_fkey" FOREIGN KEY ("plataforma_id") REFERENCES "public"."plataformas"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."canal_modalidade_mapeamento"
    ADD CONSTRAINT "canal_modalidade_mapeamento_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."categoria_bom_regras"
    ADD CONSTRAINT "categoria_bom_regras_categoria_componente_id_fkey" FOREIGN KEY ("categoria_componente_id") REFERENCES "public"."categorias"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."categoria_bom_regras"
    ADD CONSTRAINT "categoria_bom_regras_categoria_pai_id_fkey" FOREIGN KEY ("categoria_pai_id") REFERENCES "public"."categorias"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."categorias"
    ADD CONSTRAINT "categorias_categoria_pai_id_fkey" FOREIGN KEY ("categoria_pai_id") REFERENCES "public"."categorias"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."channel_connections"
    ADD CONSTRAINT "channel_connections_bling_integration_id_fkey" FOREIGN KEY ("bling_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."channel_connections"
    ADD CONSTRAINT "channel_connections_channel_id_fkey" FOREIGN KEY ("channel_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."channel_connections"
    ADD CONSTRAINT "channel_connections_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."channel_connections"
    ADD CONSTRAINT "channel_connections_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."componentes_ordem_producao"
    ADD CONSTRAINT "componentes_ordem_producao_componente_id_fkey" FOREIGN KEY ("componente_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."componentes_ordem_producao"
    ADD CONSTRAINT "componentes_ordem_producao_ordem_producao_id_fkey" FOREIGN KEY ("ordem_producao_id") REFERENCES "public"."ordens_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conferencias_arquivo"
    ADD CONSTRAINT "conferencias_arquivo_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id");



ALTER TABLE ONLY "public"."conferencias_arquivo"
    ADD CONSTRAINT "conferencias_arquivo_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."contextos_producao"
    ADD CONSTRAINT "contextos_producao_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."contextos_producao"
    ADD CONSTRAINT "contextos_producao_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."contextos_producao"
    ADD CONSTRAINT "contextos_producao_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_unidade_destino_id_fkey" FOREIGN KEY ("unidade_destino_id") REFERENCES "public"."unidades_medida"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_unidade_origem_id_fkey" FOREIGN KEY ("unidade_origem_id") REFERENCES "public"."unidades_medida"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."demanda_estoque_processado"
    ADD CONSTRAINT "demanda_estoque_processado_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id");



ALTER TABLE ONLY "public"."demanda_estoque_processado"
    ADD CONSTRAINT "demanda_estoque_processado_item_id_fkey" FOREIGN KEY ("item_id") REFERENCES "public"."itens_demanda"("id");



ALTER TABLE ONLY "public"."demanda_estoque_processado"
    ADD CONSTRAINT "demanda_estoque_processado_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."demanda_estoque_processado"
    ADD CONSTRAINT "demanda_estoque_processado_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "public"."usuarios"("id");



ALTER TABLE ONLY "public"."demandas_item_origem"
    ADD CONSTRAINT "demandas_item_origem_demanda_item_id_fkey" FOREIGN KEY ("demanda_item_id") REFERENCES "public"."itens_demanda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."demandas_item_origem"
    ADD CONSTRAINT "demandas_item_origem_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."demandas_overrides"
    ADD CONSTRAINT "demandas_overrides_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."demandas_overrides"
    ADD CONSTRAINT "demandas_overrides_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "public"."usuarios"("id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_demanda_origem_id_fkey" FOREIGN KEY ("demanda_origem_id") REFERENCES "public"."demandas_producao"("id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_editado_por_fkey" FOREIGN KEY ("editado_por") REFERENCES "public"."usuarios"("id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_modalidade_id_fkey" FOREIGN KEY ("modalidade_id") REFERENCES "public"."modalidades_logisticas"("id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_publicado_por_fkey" FOREIGN KEY ("publicado_por") REFERENCES "public"."usuarios"("id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_responsavel_id_fkey" FOREIGN KEY ("responsavel_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."entrega_producao"
    ADD CONSTRAINT "entrega_producao_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."entrega_producao"
    ADD CONSTRAINT "entrega_producao_item_demanda_id_fkey" FOREIGN KEY ("item_demanda_id") REFERENCES "public"."itens_demanda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."erp_marketplace_links"
    ADD CONSTRAINT "erp_marketplace_links_channel_id_fkey" FOREIGN KEY ("channel_id") REFERENCES "public"."canais_venda"("id");



ALTER TABLE ONLY "public"."erp_marketplace_links"
    ADD CONSTRAINT "erp_marketplace_links_erp_integration_id_fkey" FOREIGN KEY ("erp_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."erp_marketplace_links"
    ADD CONSTRAINT "erp_marketplace_links_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_deposito_id_fkey" FOREIGN KEY ("deposito_id") REFERENCES "public"."depositos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."eventos_auditoria"
    ADD CONSTRAINT "eventos_auditoria_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."eventos_pedido"
    ADD CONSTRAINT "eventos_pedido_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."eventos_producao_v2"
    ADD CONSTRAINT "eventos_producao_v2_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."eventos_producao_v2"
    ADD CONSTRAINT "eventos_producao_v2_item_demanda_id_fkey" FOREIGN KEY ("item_demanda_id") REFERENCES "public"."itens_demanda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."eventos_producao_v2"
    ADD CONSTRAINT "eventos_producao_v2_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "public"."usuarios"("id");



ALTER TABLE ONLY "public"."execucoes_ai_item"
    ADD CONSTRAINT "execucoes_ai_item_batch_id_fkey" FOREIGN KEY ("batch_id") REFERENCES "public"."execucoes_ai_batch"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ficha_tecnica_classificacao_pendente"
    ADD CONSTRAINT "ficha_tecnica_classificacao_pendente_componente_id_fkey" FOREIGN KEY ("componente_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ficha_tecnica_classificacao_pendente"
    ADD CONSTRAINT "ficha_tecnica_classificacao_pendente_ficha_tecnica_id_fkey" FOREIGN KEY ("ficha_tecnica_id") REFERENCES "public"."ficha_tecnica"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ficha_tecnica_classificacao_pendente"
    ADD CONSTRAINT "ficha_tecnica_classificacao_pendente_produto_pai_id_fkey" FOREIGN KEY ("produto_pai_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_componente_id_fkey" FOREIGN KEY ("componente_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_produto_pai_id_fkey" FOREIGN KEY ("produto_pai_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."consolidacoes_pedido"
    ADD CONSTRAINT "fk_consolidacoes_channel" FOREIGN KEY ("channel_id") REFERENCES "public"."canais_venda"("id");



ALTER TABLE ONLY "public"."demandas_pedidos"
    ADD CONSTRAINT "fk_demandas_pedidos_demanda" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."demandas_pedidos"
    ADD CONSTRAINT "fk_demandas_pedidos_pedido" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "fk_produtos_parent_id" FOREIGN KEY ("parent_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."fornecedor_insumos"
    ADD CONSTRAINT "fornecedor_insumos_fornecedor_id_fkey" FOREIGN KEY ("fornecedor_id") REFERENCES "public"."fornecedores"("id");



ALTER TABLE ONLY "public"."fornecedor_insumos"
    ADD CONSTRAINT "fornecedor_insumos_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."installed_integrations"
    ADD CONSTRAINT "installed_integrations_app_profile_id_fkey" FOREIGN KEY ("app_profile_id") REFERENCES "public"."integration_app_profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."installed_integrations"
    ADD CONSTRAINT "installed_integrations_parent_integration_id_fkey" FOREIGN KEY ("parent_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."integracao_canais_config"
    ADD CONSTRAINT "integracao_canais_config_bling_integration_id_fkey" FOREIGN KEY ("bling_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."integracao_canais_config"
    ADD CONSTRAINT "integracao_canais_config_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."integracao_canais_config"
    ADD CONSTRAINT "integracao_canais_config_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."integracao_canais_config"
    ADD CONSTRAINT "integracao_canais_config_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."integration_mapping_rules"
    ADD CONSTRAINT "integration_mapping_rules_erp_marketplace_link_id_fkey" FOREIGN KEY ("erp_marketplace_link_id") REFERENCES "public"."erp_marketplace_links"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."integration_mapping_rules"
    ADD CONSTRAINT "integration_mapping_rules_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."integration_mapping_rules"
    ADD CONSTRAINT "integration_mapping_rules_module_id_fkey" FOREIGN KEY ("module_id") REFERENCES "public"."integration_modules"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."integration_refresh_logs"
    ADD CONSTRAINT "integration_refresh_logs_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."integration_status_mappings"
    ADD CONSTRAINT "integration_status_mappings_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."integration_status_mappings"
    ADD CONSTRAINT "integration_status_mappings_internal_situacao_pedido_id_fkey" FOREIGN KEY ("internal_situacao_pedido_id") REFERENCES "public"."situacoes_pedido"("id");



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_id_produto_miolo_fkey" FOREIGN KEY ("id_produto_miolo") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."itens_ordem_compra"
    ADD CONSTRAINT "itens_ordem_compra_ordem_compra_id_fkey" FOREIGN KEY ("ordem_compra_id") REFERENCES "public"."ordens_compra"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_ordem_compra"
    ADD CONSTRAINT "itens_ordem_compra_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."itens_pedido_bling"
    ADD CONSTRAINT "itens_pedido_bling_pedido_bling_id_fkey" FOREIGN KEY ("pedido_bling_id") REFERENCES "public"."pedidos_bling"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_pedido"
    ADD CONSTRAINT "itens_pedido_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_pedido"
    ADD CONSTRAINT "itens_pedido_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."janelas_despacho_execucoes"
    ADD CONSTRAINT "janelas_despacho_execucoes_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."janelas_despacho_execucoes"
    ADD CONSTRAINT "janelas_despacho_execucoes_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."janelas_despacho_execucoes"
    ADD CONSTRAINT "janelas_despacho_execucoes_modalidade_id_fkey" FOREIGN KEY ("modalidade_id") REFERENCES "public"."modalidades_logisticas"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_equipe_id_fkey" FOREIGN KEY ("equipe_id") REFERENCES "public"."setores"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_ordem_producao_id_fkey" FOREIGN KEY ("ordem_producao_id") REFERENCES "public"."ordens_producao"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."marketplace_order_effects"
    ADD CONSTRAINT "marketplace_order_effects_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."marketplace_order_effects"
    ADD CONSTRAINT "marketplace_order_effects_transition_id_fkey" FOREIGN KEY ("transition_id") REFERENCES "public"."marketplace_order_transitions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."marketplace_order_transitions"
    ADD CONSTRAINT "marketplace_order_transitions_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."marketplace_order_transitions"
    ADD CONSTRAINT "marketplace_order_transitions_webhook_event_id_fkey" FOREIGN KEY ("webhook_event_id") REFERENCES "public"."webhook_events"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."mensagem_chat_shopee"
    ADD CONSTRAINT "mensagem_chat_shopee_installed_integration_id_fkey" FOREIGN KEY ("installed_integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."mensagem_chat_shopee"
    ADD CONSTRAINT "mensagem_chat_shopee_webhook_event_id_fkey" FOREIGN KEY ("webhook_event_id") REFERENCES "public"."webhook_events"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."metodos_envio_observados"
    ADD CONSTRAINT "metodos_envio_observados_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."metodos_envio_observados"
    ADD CONSTRAINT "metodos_envio_observados_modalidade_id_fkey" FOREIGN KEY ("modalidade_id") REFERENCES "public"."modalidades_logisticas"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_deposito_id_fkey" FOREIGN KEY ("deposito_id") REFERENCES "public"."depositos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_item_demanda_id_fkey" FOREIGN KEY ("item_demanda_id") REFERENCES "public"."itens_demanda"("id");



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_parent_movimento_id_fkey" FOREIGN KEY ("parent_movimento_id") REFERENCES "public"."movimentacoes_estoque"("id");



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."oauth_authorization_sessions"
    ADD CONSTRAINT "oauth_authorization_sessions_app_profile_id_fkey" FOREIGN KEY ("app_profile_id") REFERENCES "public"."integration_app_profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."oauth_authorization_sessions"
    ADD CONSTRAINT "oauth_authorization_sessions_installed_integration_id_fkey" FOREIGN KEY ("installed_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_fornecedor_id_fkey" FOREIGN KEY ("fornecedor_id") REFERENCES "public"."fornecedores"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_responsavel_id_fkey" FOREIGN KEY ("responsavel_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."order_identity_corrections"
    ADD CONSTRAINT "order_identity_corrections_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pedido_integration_refs"
    ADD CONSTRAINT "pedido_integration_refs_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedido_integration_refs"
    ADD CONSTRAINT "pedido_integration_refs_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pedido_snapshots"
    ADD CONSTRAINT "pedido_snapshots_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pedidos_bling"
    ADD CONSTRAINT "pedidos_bling_bling_integration_id_fkey" FOREIGN KEY ("bling_integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."pedidos_bling"
    ADD CONSTRAINT "pedidos_bling_integracao_instancia_id_fkey" FOREIGN KEY ("integracao_instancia_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_erp_integration_id_fkey" FOREIGN KEY ("erp_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."pedidos_mercadolivre"
    ADD CONSTRAINT "pedidos_mercadolivre_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_modalidade_logistica_id_fkey" FOREIGN KEY ("modalidade_logistica_id") REFERENCES "public"."modalidades_logisticas"("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_modalidade_regra_id_fkey" FOREIGN KEY ("modalidade_regra_id") REFERENCES "public"."regras_classificacao_modalidade"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos_nao_classificados"
    ADD CONSTRAINT "pedidos_nao_classificados_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pedidos_nao_classificados"
    ADD CONSTRAINT "pedidos_nao_classificados_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pedidos_nao_classificados"
    ADD CONSTRAINT "pedidos_nao_classificados_resolvido_por_fkey" FOREIGN KEY ("resolvido_por") REFERENCES "public"."usuarios"("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_pedido_bling_id_fkey" FOREIGN KEY ("pedido_bling_id") REFERENCES "public"."pedidos_bling"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_pedido_mercadolivre_id_fkey" FOREIGN KEY ("pedido_mercadolivre_id") REFERENCES "public"."pedidos_mercadolivre"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_pedido_shopee_id_fkey" FOREIGN KEY ("pedido_shopee_id") REFERENCES "public"."pedidos_shopee"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_regra_logistica_integracao_id_fkey" FOREIGN KEY ("regra_logistica_integracao_id") REFERENCES "public"."regras_logisticas_integracao"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_situacao_pedido_id_fkey" FOREIGN KEY ("situacao_pedido_id") REFERENCES "public"."situacoes_pedido"("id");



ALTER TABLE ONLY "public"."pending_marketplace_enrichments"
    ADD CONSTRAINT "pending_marketplace_enrichments_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pending_marketplace_enrichments"
    ADD CONSTRAINT "pending_marketplace_enrichments_matched_pedido_id_fkey" FOREIGN KEY ("matched_pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pending_order_reconciliations"
    ADD CONSTRAINT "pending_order_reconciliations_erp_integration_id_fkey" FOREIGN KEY ("erp_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pending_order_reconciliations"
    ADD CONSTRAINT "pending_order_reconciliations_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."permissoes_setor"
    ADD CONSTRAINT "permissoes_setor_recurso_id_fkey" FOREIGN KEY ("recurso_id") REFERENCES "public"."recursos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."permissoes_setor"
    ADD CONSTRAINT "permissoes_setor_setor_id_fkey" FOREIGN KEY ("setor_id") REFERENCES "public"."setores"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."previsao_consumo_demanda"
    ADD CONSTRAINT "previsao_consumo_demanda_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."previsao_consumo_demanda"
    ADD CONSTRAINT "previsao_consumo_demanda_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."produto_alias_conflitos"
    ADD CONSTRAINT "produto_alias_conflitos_produto_alias_id_fkey" FOREIGN KEY ("produto_alias_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."produto_alias_conflitos"
    ADD CONSTRAINT "produto_alias_conflitos_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_anuncios"
    ADD CONSTRAINT "produto_anuncios_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_anuncios"
    ADD CONSTRAINT "produto_anuncios_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."produto_eixo_opcao_componentes"
    ADD CONSTRAINT "produto_eixo_opcao_componentes_componente_produto_id_fkey" FOREIGN KEY ("componente_produto_id") REFERENCES "public"."produtos"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."produto_eixo_opcao_componentes"
    ADD CONSTRAINT "produto_eixo_opcao_componentes_opcao_id_fkey" FOREIGN KEY ("opcao_id") REFERENCES "public"."produto_eixo_opcoes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_eixo_opcoes"
    ADD CONSTRAINT "produto_eixo_opcoes_eixo_id_fkey" FOREIGN KEY ("eixo_id") REFERENCES "public"."produto_eixos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_pai_eixos"
    ADD CONSTRAINT "produto_pai_eixos_eixo_id_fkey" FOREIGN KEY ("eixo_id") REFERENCES "public"."produto_eixos"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."produto_pai_eixos"
    ADD CONSTRAINT "produto_pai_eixos_produto_pai_id_fkey" FOREIGN KEY ("produto_pai_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_precos"
    ADD CONSTRAINT "produto_precos_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_precos"
    ADD CONSTRAINT "produto_precos_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_sku_historico"
    ADD CONSTRAINT "produto_sku_historico_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_tags"
    ADD CONSTRAINT "produto_tags_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_tags"
    ADD CONSTRAINT "produto_tags_tag_id_fkey" FOREIGN KEY ("tag_id") REFERENCES "public"."tags"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_variacao_backfill_revisao"
    ADD CONSTRAINT "produto_variacao_backfill_revisao_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produto_variacao_valores"
    ADD CONSTRAINT "produto_variacao_valores_eixo_id_fkey" FOREIGN KEY ("eixo_id") REFERENCES "public"."produto_eixos"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."produto_variacao_valores"
    ADD CONSTRAINT "produto_variacao_valores_opcao_id_fkey" FOREIGN KEY ("opcao_id") REFERENCES "public"."produto_eixo_opcoes"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."produto_variacao_valores"
    ADD CONSTRAINT "produto_variacao_valores_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_categoria_id_fkey" FOREIGN KEY ("categoria_id") REFERENCES "public"."categorias"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."produtos_externos"
    ADD CONSTRAINT "produtos_externos_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_perfil_fiscal_id_fkey" FOREIGN KEY ("perfil_fiscal_id") REFERENCES "public"."perfis_fiscais"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_setor_responsavel_id_fkey" FOREIGN KEY ("setor_responsavel_id") REFERENCES "public"."setores"("id");



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_unidade_medida_id_fkey" FOREIGN KEY ("unidade_medida_id") REFERENCES "public"."unidades_medida"("id");



ALTER TABLE ONLY "public"."regra_logistica_modalidades"
    ADD CONSTRAINT "regra_logistica_modalidades_modalidade_id_fkey" FOREIGN KEY ("modalidade_id") REFERENCES "public"."modalidades_logisticas"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regra_logistica_modalidades"
    ADD CONSTRAINT "regra_logistica_modalidades_regra_id_fkey" FOREIGN KEY ("regra_id") REFERENCES "public"."regras_logisticas_integracao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regras_classificacao_modalidade"
    ADD CONSTRAINT "regras_classificacao_modalidade_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regras_classificacao_modalidade"
    ADD CONSTRAINT "regras_classificacao_modalidade_modalidade_id_fkey" FOREIGN KEY ("modalidade_id") REFERENCES "public"."modalidades_logisticas"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regras_consolidacao_canal"
    ADD CONSTRAINT "regras_consolidacao_canal_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regras_logisticas_canal"
    ADD CONSTRAINT "regras_logisticas_canal_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regras_logisticas_canal"
    ADD CONSTRAINT "regras_logisticas_canal_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."regras_logisticas_canal"
    ADD CONSTRAINT "regras_logisticas_canal_ponto_coleta_id_fkey" FOREIGN KEY ("ponto_coleta_id") REFERENCES "public"."pontos_coleta"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."regras_logisticas_integracao"
    ADD CONSTRAINT "regras_logisticas_integracao_marketplace_integration_id_fkey" FOREIGN KEY ("marketplace_integration_id") REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regras_logisticas_integracao"
    ADD CONSTRAINT "regras_logisticas_integracao_modalidade_id_fkey" FOREIGN KEY ("modalidade_id") REFERENCES "public"."modalidades_logisticas"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."regras_logisticas_integracao"
    ADD CONSTRAINT "regras_logisticas_integracao_ponto_coleta_id_fkey" FOREIGN KEY ("ponto_coleta_id") REFERENCES "public"."pontos_coleta"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."sinalizacoes_demanda"
    ADD CONSTRAINT "sinalizacoes_demanda_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sync_status_errors"
    ADD CONSTRAINT "sync_status_errors_batch_id_fkey" FOREIGN KEY ("batch_id") REFERENCES "public"."sync_status_batches"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."templates_obs_canal"
    ADD CONSTRAINT "templates_obs_canal_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_situacao_destino_id_fkey" FOREIGN KEY ("situacao_destino_id") REFERENCES "public"."situacoes_pedido"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_situacao_origem_id_fkey" FOREIGN KEY ("situacao_origem_id") REFERENCES "public"."situacoes_pedido"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."usuarios"
    ADD CONSTRAINT "usuarios_setor_id_fkey" FOREIGN KEY ("setor_id") REFERENCES "public"."setores"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."grupo_mensagens_chat_shopee"
    ADD CONSTRAINT "v2_bundle_messages_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."mensagem_chat_shopee"("id");



ALTER TABLE ONLY "public"."vinculos_bling"
    ADD CONSTRAINT "vinculos_bling_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."vinculos_integracao_pedido"
    ADD CONSTRAINT "vinculos_integracao_pedido_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."webhook_event_attempts"
    ADD CONSTRAINT "webhook_event_attempts_webhook_event_id_fkey" FOREIGN KEY ("webhook_event_id") REFERENCES "public"."webhook_events"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."webhook_events"
    ADD CONSTRAINT "webhook_events_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE SET NULL;



CREATE POLICY "Allow authenticated read access" ON "public"."cache_dashboard_pedidos" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."logs_execucao_ia" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."mensagem_chat_shopee" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."personalizacoes_pedido" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Apenas service_role pode gerenciar vínculos" ON "public"."erp_marketplace_links" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Enable read access for all users" ON "public"."integration_modules" FOR SELECT USING (true);



CREATE POLICY "Usuários autenticados podem atualizar consolidacoes" ON "public"."consolidacoes_pedido" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Usuários autenticados podem atualizar demandas_overrides" ON "public"."demandas_overrides" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "Usuários autenticados podem criar consolidacoes" ON "public"."consolidacoes_pedido" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Usuários autenticados podem criar demandas_overrides" ON "public"."demandas_overrides" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Usuários autenticados podem deletar demandas_overrides" ON "public"."demandas_overrides" FOR DELETE TO "authenticated" USING (true);



CREATE POLICY "Usuários autenticados podem ver consolidacoes" ON "public"."consolidacoes_pedido" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Usuários autenticados podem ver demandas_overrides" ON "public"."demandas_overrides" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Usuários autenticados podem visualizar vínculos" ON "public"."erp_marketplace_links" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."agenda_recursos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."alertas_demanda" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."archive_manifests" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "authenticated_delete_canal_modalidade" ON "public"."canal_modalidade_mapeamento" FOR DELETE TO "authenticated" USING (true);



CREATE POLICY "authenticated_delete_pedidos_nao_classificados" ON "public"."pedidos_nao_classificados" FOR DELETE TO "authenticated" USING (true);



CREATE POLICY "authenticated_delete_regras_consolidacao" ON "public"."regras_consolidacao_canal" FOR DELETE TO "authenticated" USING (true);



CREATE POLICY "authenticated_delete_regras_logisticas_integracao" ON "public"."regras_logisticas_integracao" FOR DELETE TO "authenticated" USING (true);



CREATE POLICY "authenticated_insert_canal_modalidade" ON "public"."canal_modalidade_mapeamento" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "authenticated_insert_pedidos_nao_classificados" ON "public"."pedidos_nao_classificados" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "authenticated_insert_regras_consolidacao" ON "public"."regras_consolidacao_canal" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "authenticated_insert_regras_logisticas_integracao" ON "public"."regras_logisticas_integracao" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "authenticated_manage_integration_mapping_rules" ON "public"."integration_mapping_rules" TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "authenticated_select_regras_logisticas_integracao" ON "public"."regras_logisticas_integracao" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "authenticated_update_canal_modalidade" ON "public"."canal_modalidade_mapeamento" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "authenticated_update_pedidos_nao_classificados" ON "public"."pedidos_nao_classificados" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "authenticated_update_regras_consolidacao" ON "public"."regras_consolidacao_canal" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "authenticated_update_regras_logisticas_integracao" ON "public"."regras_logisticas_integracao" FOR UPDATE TO "authenticated" USING (true);



CREATE POLICY "authenticated_view_canal_modalidade" ON "public"."canal_modalidade_mapeamento" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "authenticated_view_pedidos_nao_classificados" ON "public"."pedidos_nao_classificados" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "authenticated_view_regras_consolidacao" ON "public"."regras_consolidacao_canal" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."cache_dashboard_pedidos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."canais_venda" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."canal_modalidade_mapeamento" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."categoria_bom_regras" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."categorias" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."channel_connections" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."componentes_ordem_producao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conferencias_arquivo" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."configuracoes_aplicacao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."consolidacoes_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."contas_bling" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."contextos_producao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conversoes_uom_produto" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."demanda_alocacoes_estoque" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."demanda_estoque_processado" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."demandas_item_origem" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."demandas_overrides" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."demandas_pedidos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."demandas_producao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."depositos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."entity_correlation_mapping" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."entrega_producao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."erp_marketplace_links" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."estoque_atual" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."eventos_auditoria" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."eventos_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."eventos_producao_v2" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."execucoes_ai_batch" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."execucoes_ai_item" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."feedback_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."ficha_tecnica" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."fornecedor_insumos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."fornecedores" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."grupo_mensagens_chat_shopee" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."installed_integrations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integracao_canais_config" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integration_account_routing" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integration_app_profiles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "integration_app_profiles_deny_all" ON "public"."integration_app_profiles" AS RESTRICTIVE TO "authenticated", "anon" USING (false) WITH CHECK (false);



ALTER TABLE "public"."integration_mapping_rules" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integration_modules" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integration_refresh_logs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integration_secret_values" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "integration_secret_values_deny_all" ON "public"."integration_secret_values" AS RESTRICTIVE TO "authenticated", "anon" USING (false) WITH CHECK (false);



ALTER TABLE "public"."integration_status_mappings" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."itens_demanda" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."itens_ordem_compra" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."itens_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."itens_pedido_bling" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."janelas_despacho_execucoes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "janelas_despacho_execucoes_rw" ON "public"."janelas_despacho_execucoes" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."logs_execucao_ia" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."logs_producao_diaria" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."manutencao_status_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."marketplace_order_effects" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."marketplace_order_transitions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mensagem_chat_shopee" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."metodos_envio_observados" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."modalidades_logisticas" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."movimentacoes_estoque" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notificacoes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."oauth_authorization_sessions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "oauth_authorization_sessions_deny_all" ON "public"."oauth_authorization_sessions" AS RESTRICTIVE TO "authenticated", "anon" USING (false) WITH CHECK (false);



ALTER TABLE "public"."ordens_compra" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."ordens_producao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."order_identity_corrections" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedido_ingest_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedido_integration_refs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedido_snapshots" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedidos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedidos_bling" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedidos_mercadolivre" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedidos_nao_classificados" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pedidos_shopee" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pending_marketplace_enrichments" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pending_order_reconciliations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."perfis_fiscais" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "perfis_fiscais_authenticated_all" ON "public"."perfis_fiscais" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."permissoes_setor" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."personalizacoes_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."plataformas" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pontos_coleta" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."preferencias_ux_usuario" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."previsao_consumo_demanda" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."produto_alias_conflitos" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_alias_conflitos_authenticated_all" ON "public"."produto_alias_conflitos" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_anuncios" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_anuncios_authenticated_all" ON "public"."produto_anuncios" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_eixo_opcao_componentes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_eixo_opcao_componentes_authenticated_all" ON "public"."produto_eixo_opcao_componentes" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_eixo_opcoes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_eixo_opcoes_authenticated_all" ON "public"."produto_eixo_opcoes" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_eixos" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_eixos_authenticated_all" ON "public"."produto_eixos" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_pai_eixos" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_pai_eixos_authenticated_all" ON "public"."produto_pai_eixos" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_precos" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_precos_authenticated_all" ON "public"."produto_precos" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_sku_historico" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_sku_historico_authenticated_all" ON "public"."produto_sku_historico" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_tags" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_tags_authenticated_all" ON "public"."produto_tags" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produto_variacao_valores" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "produto_variacao_valores_authenticated_all" ON "public"."produto_variacao_valores" TO "authenticated" USING (true) WITH CHECK (true);



ALTER TABLE "public"."produtos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."produtos_externos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."recursos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."recursos_produtivos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."regras_classificacao_modalidade" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."regras_consolidacao_canal" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."regras_logisticas_canal" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."regras_logisticas_integracao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."regras_priorizacao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."setores" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sinalizacoes_demanda" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."situacoes_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sync_status_batches" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sync_status_errors" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."system_events_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tags" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."task_execution_logs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."templates_obs_canal" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."transicoes_situacao" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."unidades_medida" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."usuarios" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."vinculos_bling" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."vinculos_integracao_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."webhook_event_attempts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."webhook_events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."webhook_logs" ENABLE ROW LEVEL SECURITY;


GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";



REVOKE ALL ON FUNCTION "public"."accept_reliable_webhook_event"("p_source" "text", "p_dedupe_scope" "text", "p_dedupe_key" "text", "p_provider_event_id" "text", "p_payload_hash" "text", "p_raw_payload" "jsonb", "p_raw_body" "text", "p_received_at" timestamp with time zone, "p_correlation_id" "uuid", "p_resolved_order_id" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."accept_reliable_webhook_event"("p_source" "text", "p_dedupe_scope" "text", "p_dedupe_key" "text", "p_provider_event_id" "text", "p_payload_hash" "text", "p_raw_payload" "jsonb", "p_raw_body" "text", "p_received_at" timestamp with time zone, "p_correlation_id" "uuid", "p_resolved_order_id" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."apply_marketplace_order_event"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb", "p_event" "jsonb", "p_projection_enabled" boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."apply_marketplace_order_event"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb", "p_event" "jsonb", "p_projection_enabled" boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."associar_canal_modalidade"("p_module_id" "text", "p_chave" "text", "p_modalidade_id" integer, "p_campo_origem" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."associar_canal_modalidade"("p_module_id" "text", "p_chave" "text", "p_modalidade_id" integer, "p_campo_origem" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."associar_canal_modalidade"("p_module_id" "text", "p_chave" "text", "p_modalidade_id" integer, "p_campo_origem" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."atualizar_chave_combinacao_variacao"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."atualizar_chave_combinacao_variacao"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."auditar_cadastro_produto"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."auditar_cadastro_produto"() TO "service_role";



GRANT ALL ON FUNCTION "public"."backfill_despachado_em"("p_limite" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."backfill_despachado_em"("p_limite" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."backfill_despachado_em"("p_limite" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."backfill_modalidade_pedidos"("p_limite" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."backfill_modalidade_pedidos"("p_limite" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."backfill_modalidade_pedidos"("p_limite" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."bom_efetiva_produto"("p_produto_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."bom_efetiva_produto"("p_produto_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."bom_efetiva_produto"("p_produto_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."bom_efetiva_produtos"("p_produto_ids" integer[]) TO "anon";
GRANT ALL ON FUNCTION "public"."bom_efetiva_produtos"("p_produto_ids" integer[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."bom_efetiva_produtos"("p_produto_ids" integer[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."calcular_saldo_a_processar"("p_item_id" character varying, "p_produto_id" character varying, "p_quantidade_necessaria" numeric) TO "anon";
GRANT ALL ON FUNCTION "public"."calcular_saldo_a_processar"("p_item_id" character varying, "p_produto_id" character varying, "p_quantidade_necessaria" numeric) TO "authenticated";
GRANT ALL ON FUNCTION "public"."calcular_saldo_a_processar"("p_item_id" character varying, "p_produto_id" character varying, "p_quantidade_necessaria" numeric) TO "service_role";



GRANT ALL ON FUNCTION "public"."calcular_score_priorizacao_base"("p_modalidade_logistica" "text", "p_is_flex" boolean, "p_fulfillment" boolean, "p_classificacao_cliente" "text", "p_horario_coleta" time without time zone, "p_data_entrega" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."calcular_score_priorizacao_base"("p_modalidade_logistica" "text", "p_is_flex" boolean, "p_fulfillment" boolean, "p_classificacao_cliente" "text", "p_horario_coleta" time without time zone, "p_data_entrega" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."calcular_score_priorizacao_base"("p_modalidade_logistica" "text", "p_is_flex" boolean, "p_fulfillment" boolean, "p_classificacao_cliente" "text", "p_horario_coleta" time without time zone, "p_data_entrega" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."canais_envio_observados"("p_integration_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."canais_envio_observados"("p_integration_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."canais_envio_observados"("p_integration_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."cancelar_alocacao"("p_correlation_id" character varying, "p_motivo" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."cancelar_alocacao"("p_correlation_id" character varying, "p_motivo" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."cancelar_alocacao"("p_correlation_id" character varying, "p_motivo" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."cascade_tipo_pai_para_variacoes"() TO "anon";
GRANT ALL ON FUNCTION "public"."cascade_tipo_pai_para_variacoes"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cascade_tipo_pai_para_variacoes"() TO "service_role";



GRANT ALL ON FUNCTION "public"."categorizar_demanda_temporal"("p_data_entrega" "date", "p_horario_coleta" time without time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."categorizar_demanda_temporal"("p_data_entrega" "date", "p_horario_coleta" time without time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."categorizar_demanda_temporal"("p_data_entrega" "date", "p_horario_coleta" time without time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."classificar_pedido_modalidade"("p_pedido_id" integer, "p_agora" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."classificar_pedido_modalidade"("p_pedido_id" integer, "p_agora" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."classificar_pedido_modalidade"("p_pedido_id" integer, "p_agora" timestamp with time zone) TO "service_role";



REVOKE ALL ON FUNCTION "public"."cleanup_archived_ingest_hot_data"("p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."cleanup_archived_ingest_hot_data"("p_limit" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."coleta_do_pedido"("p_modalidade_id" integer, "p_integration_id" integer, "p_referencia" timestamp with time zone, "p_agora" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."coleta_do_pedido"("p_modalidade_id" integer, "p_integration_id" integer, "p_referencia" timestamp with time zone, "p_agora" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."coleta_do_pedido"("p_modalidade_id" integer, "p_integration_id" integer, "p_referencia" timestamp with time zone, "p_agora" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."consolidar_casar_refs"("p_refs" "text"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."consolidar_casar_refs"("p_refs" "text"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."consolidar_casar_refs"("p_refs" "text"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."contar_pedidos_novos_apos_edicao"("p_demanda_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."contar_pedidos_novos_apos_edicao"("p_demanda_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."contar_pedidos_novos_apos_edicao"("p_demanda_id" bigint) TO "service_role";



REVOKE ALL ON FUNCTION "public"."correct_canonical_order_identity"("p_pedido_id" bigint, "p_marketplace_module_id" "text", "p_marketplace_order_id" "text", "p_reason" "text", "p_actor_id" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."correct_canonical_order_identity"("p_pedido_id" bigint, "p_marketplace_module_id" "text", "p_marketplace_order_id" "text", "p_reason" "text", "p_actor_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."correct_canonical_order_identity"("p_pedido_id" bigint, "p_marketplace_module_id" "text", "p_marketplace_order_id" "text", "p_reason" "text", "p_actor_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."correct_canonical_order_identity"("p_pedido_id" bigint, "p_marketplace_module_id" "text", "p_marketplace_order_id" "text", "p_reason" "text", "p_actor_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."demanda_atrasada"("p_demanda_id" integer, "p_agora" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."demanda_atrasada"("p_demanda_id" integer, "p_agora" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."demanda_atrasada"("p_demanda_id" integer, "p_agora" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."derivar_modalidade_logistica"("p_canal_venda_id" bigint, "p_servico_logistico" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."derivar_modalidade_logistica"("p_canal_venda_id" bigint, "p_servico_logistico" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."derivar_modalidade_logistica"("p_canal_venda_id" bigint, "p_servico_logistico" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_aba_do_bucket"("p_bucket" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_aba_do_bucket"("p_bucket" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_aba_do_bucket"("p_bucket" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_arvore"("p_data" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_arvore"("p_data" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_arvore"("p_data" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_bucket_prazo"("p_data_limite" timestamp with time zone, "p_data" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_bucket_prazo"("p_data_limite" timestamp with time zone, "p_data" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_bucket_prazo"("p_data_limite" timestamp with time zone, "p_data" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_cancelar_demanda"("p_demanda_id" integer, "p_motivo" "text", "p_user_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_cancelar_demanda"("p_demanda_id" integer, "p_motivo" "text", "p_user_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_cancelar_demanda"("p_demanda_id" integer, "p_motivo" "text", "p_user_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_composicao_situacao"("p_data" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_composicao_situacao"("p_data" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_composicao_situacao"("p_data" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_consolidar_pedidos"("p_pedido_ids" integer[]) TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_consolidar_pedidos"("p_pedido_ids" integer[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_consolidar_pedidos"("p_pedido_ids" integer[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_escopo_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_escopo_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_escopo_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_escopo_pedidos"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_escopo_pedidos"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_escopo_pedidos"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_esteira_relativo"() TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_esteira_relativo"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_esteira_relativo"() TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_excluir_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_excluir_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_excluir_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_fechar_corte"("p_integration_id" integer, "p_modalidade_id" integer, "p_janela_em" timestamp with time zone, "p_user_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_fechar_corte"("p_integration_id" integer, "p_modalidade_id" integer, "p_janela_em" timestamp with time zone, "p_user_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_fechar_corte"("p_integration_id" integer, "p_modalidade_id" integer, "p_janela_em" timestamp with time zone, "p_user_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_kit_componentes"("p_produto_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_kit_componentes"("p_produto_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_kit_componentes"("p_produto_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_lancar_escopo"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_lancar_escopo"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_lancar_escopo"("p_integration_id" integer, "p_modalidade_id" integer, "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_lancar_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_lancar_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_lancar_lote"("p_integration_id" integer, "p_modalidade_ids" integer[], "p_horizonte" "text"[], "p_data" "date", "p_nome" "text", "p_user_id" "text", "p_observacoes" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_lancar_pedidos"("p_pedido_ids" integer[], "p_nome" "text", "p_user_id" "text", "p_observacoes" "text", "p_escopo" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_lancar_pedidos"("p_pedido_ids" integer[], "p_nome" "text", "p_user_id" "text", "p_observacoes" "text", "p_escopo" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_lancar_pedidos"("p_pedido_ids" integer[], "p_nome" "text", "p_user_id" "text", "p_observacoes" "text", "p_escopo" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_lotes"("p_integration_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_lotes"("p_integration_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_lotes"("p_integration_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_materializar_itens"("p_demanda_id" integer, "p_pedido_ids" integer[], "p_ajustes" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_materializar_itens"("p_demanda_id" integer, "p_pedido_ids" integer[], "p_ajustes" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_materializar_itens"("p_demanda_id" integer, "p_pedido_ids" integer[], "p_ajustes" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_publicar_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_publicar_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_publicar_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_rascunhos_abertos"("p_data" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_rascunhos_abertos"("p_data" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_rascunhos_abertos"("p_data" "date") TO "service_role";



REVOKE ALL ON FUNCTION "public"."despacho_reaplicar_itens"("p_demanda_id" integer, "p_ajustes" "jsonb", "p_user_id" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."despacho_reaplicar_itens"("p_demanda_id" integer, "p_ajustes" "jsonb", "p_user_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_reaplicar_itens"("p_demanda_id" integer, "p_ajustes" "jsonb", "p_user_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_recalcular_compromissos"() TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_recalcular_compromissos"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_recalcular_compromissos"() TO "service_role";



GRANT ALL ON FUNCTION "public"."despacho_sincronizar_carimbo"("p_pedido_ids" integer[]) TO "anon";
GRANT ALL ON FUNCTION "public"."despacho_sincronizar_carimbo"("p_pedido_ids" integer[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."despacho_sincronizar_carimbo"("p_pedido_ids" integer[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp without time zone, "p_created_at" timestamp without time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp without time zone, "p_created_at" timestamp without time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp without time zone, "p_created_at" timestamp without time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp with time zone, "p_created_at" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp with time zone, "p_created_at" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."effective_purchase_date"("p_data_compra_marketplace" timestamp with time zone, "p_data_venda" timestamp with time zone, "p_created_at" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."enforce_marketplace_order_authority"() TO "anon";
GRANT ALL ON FUNCTION "public"."enforce_marketplace_order_authority"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."enforce_marketplace_order_authority"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."enrich_order_erp_reference"("p_pedido_id" bigint, "p_erp_integration_id" integer, "p_erp_store_id" "text", "p_erp_order_id" bigint, "p_erp_order_number" "text", "p_marketplace_order_id" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."enrich_order_erp_reference"("p_pedido_id" bigint, "p_erp_integration_id" integer, "p_erp_store_id" "text", "p_erp_order_id" bigint, "p_erp_order_number" "text", "p_marketplace_order_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."enrich_order_erp_reference"("p_pedido_id" bigint, "p_erp_integration_id" integer, "p_erp_store_id" "text", "p_erp_order_id" bigint, "p_erp_order_number" "text", "p_marketplace_order_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."enrich_order_erp_reference"("p_pedido_id" bigint, "p_erp_integration_id" integer, "p_erp_store_id" "text", "p_erp_order_id" bigint, "p_erp_order_number" "text", "p_marketplace_order_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."extrair_metodo_envio"("p_module_id" "text", "p_platform_fields" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."extrair_metodo_envio"("p_module_id" "text", "p_platform_fields" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."extrair_metodo_envio"("p_module_id" "text", "p_platform_fields" "jsonb") TO "service_role";



REVOKE ALL ON FUNCTION "public"."finalize_ingest_archive_batch"("p_dataset" "text", "p_ids" "text"[], "p_object_key" "text", "p_sha256" "text", "p_period_start" "date", "p_period_end" "date", "p_row_count" bigint, "p_schema_version" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."finalize_ingest_archive_batch"("p_dataset" "text", "p_ids" "text"[], "p_object_key" "text", "p_sha256" "text", "p_period_start" "date", "p_period_end" "date", "p_row_count" bigint, "p_schema_version" integer) TO "service_role";



GRANT ALL ON TABLE "public"."installed_integrations" TO "anon";
GRANT ALL ON TABLE "public"."installed_integrations" TO "authenticated";
GRANT ALL ON TABLE "public"."installed_integrations" TO "service_role";



GRANT ALL ON FUNCTION "public"."find_bling_integration_by_cnpj"("p_cnpj" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."find_bling_integration_by_cnpj"("p_cnpj" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."find_bling_integration_by_cnpj"("p_cnpj" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."find_bling_integration_by_company_id"("p_company_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."find_bling_integration_by_company_id"("p_company_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."find_bling_integration_by_company_id"("p_company_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."find_marketplace_by_bling_loja"("p_loja_id" "text", "p_bling_integration_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."find_marketplace_by_bling_loja"("p_loja_id" "text", "p_bling_integration_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."find_marketplace_by_bling_loja"("p_loja_id" "text", "p_bling_integration_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."find_shopee_connection"("p_bling_integration_id" bigint, "p_aggregator_store_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."find_shopee_connection"("p_bling_integration_id" bigint, "p_aggregator_store_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."find_shopee_connection"("p_bling_integration_id" bigint, "p_aggregator_store_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_atualizar_requer_revisao"() TO "anon";
GRANT ALL ON FUNCTION "public"."fn_atualizar_requer_revisao"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_atualizar_requer_revisao"() TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_canais_proximos_coleta"("p_limit" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."fn_canais_proximos_coleta"("p_limit" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_canais_proximos_coleta"("p_limit" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_contar_pedidos_por_canal"("p_canal_venda_id" integer, "p_dias" integer, "p_has_demanda" boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."fn_contar_pedidos_por_canal"("p_canal_venda_id" integer, "p_dias" integer, "p_has_demanda" boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_contar_pedidos_por_canal"("p_canal_venda_id" integer, "p_dias" integer, "p_has_demanda" boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_external_id"("p_pedido_id" integer, "p_platform" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."fn_external_id"("p_pedido_id" integer, "p_platform" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_external_id"("p_pedido_id" integer, "p_platform" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_snapshot_channel_on_insert"() TO "anon";
GRANT ALL ON FUNCTION "public"."fn_snapshot_channel_on_insert"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_snapshot_channel_on_insert"() TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_sugerir_valores_demanda"("p_canal_venda_id" integer, "p_tipo_demanda" character varying, "p_data_entrega" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."fn_sugerir_valores_demanda"("p_canal_venda_id" integer, "p_tipo_demanda" character varying, "p_data_entrega" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_sugerir_valores_demanda"("p_canal_venda_id" integer, "p_tipo_demanda" character varying, "p_data_entrega" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_validar_override_demanda"("p_campo" character varying, "p_valor_alterado" "jsonb", "p_canal_venda_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."fn_validar_override_demanda"("p_campo" character varying, "p_valor_alterado" "jsonb", "p_canal_venda_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_validar_override_demanda"("p_campo" character varying, "p_valor_alterado" "jsonb", "p_canal_venda_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_alertas_producao"() TO "anon";
GRANT ALL ON FUNCTION "public"."get_alertas_producao"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_alertas_producao"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_demandas_ativas_com_pedido"("p_pedido_externo_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."get_demandas_ativas_com_pedido"("p_pedido_externo_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_demandas_ativas_com_pedido"("p_pedido_externo_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_demandas_do_pedido"("p_pedido_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."get_demandas_do_pedido"("p_pedido_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_demandas_do_pedido"("p_pedido_id" bigint) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_demandas_por_pedido_externo"("p_pedido_externo_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."get_demandas_por_pedido_externo"("p_pedido_externo_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_demandas_por_pedido_externo"("p_pedido_externo_id" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."get_ingest_archive_batch"("p_dataset" "text", "p_before" timestamp with time zone, "p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."get_ingest_archive_batch"("p_dataset" "text", "p_before" timestamp with time zone, "p_limit" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_ledger_por_item_demanda"("p_item_id" integer, "p_demanda_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."get_ledger_por_item_demanda"("p_item_id" integer, "p_demanda_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_ledger_por_item_demanda"("p_item_id" integer, "p_demanda_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_pedidos_com_filtros_avancados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."get_pedidos_com_filtros_avancados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_pedidos_com_filtros_avancados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_pedidos_contexto_consolidacao"("p_filtro_contexto" "text", "p_canal_venda_id" integer, "p_data_limite_inicio" timestamp with time zone, "p_data_limite_fim" timestamp with time zone, "p_limit" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."get_pedidos_contexto_consolidacao"("p_filtro_contexto" "text", "p_canal_venda_id" integer, "p_data_limite_inicio" timestamp with time zone, "p_data_limite_fim" timestamp with time zone, "p_limit" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_pedidos_contexto_consolidacao"("p_filtro_contexto" "text", "p_canal_venda_id" integer, "p_data_limite_inicio" timestamp with time zone, "p_data_limite_fim" timestamp with time zone, "p_limit" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_pedidos_origem_options"() TO "anon";
GRANT ALL ON FUNCTION "public"."get_pedidos_origem_options"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_pedidos_origem_options"() TO "service_role";



GRANT ALL ON FUNCTION "public"."pedido_tem_demanda"("p_pedido_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."pedido_tem_demanda"("p_pedido_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."pedido_tem_demanda"("p_pedido_id" bigint) TO "service_role";



GRANT ALL ON TABLE "public"."canais_venda" TO "anon";
GRANT ALL ON TABLE "public"."canais_venda" TO "authenticated";
GRANT ALL ON TABLE "public"."canais_venda" TO "service_role";



GRANT ALL ON TABLE "public"."itens_pedido" TO "anon";
GRANT ALL ON TABLE "public"."itens_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_pedido" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos" TO "service_role";



GRANT ALL ON TABLE "public"."situacoes_pedido" TO "anon";
GRANT ALL ON TABLE "public"."situacoes_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."situacoes_pedido" TO "service_role";



GRANT ALL ON TABLE "public"."view_pedidos_para_consolidar" TO "anon";
GRANT ALL ON TABLE "public"."view_pedidos_para_consolidar" TO "authenticated";
GRANT ALL ON TABLE "public"."view_pedidos_para_consolidar" TO "service_role";



GRANT ALL ON FUNCTION "public"."get_pedidos_para_consolidar"("p_plataforma_id" integer, "p_is_flex" boolean, "p_data_inicio" timestamp with time zone, "p_data_fim" timestamp with time zone, "p_search" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."get_pedidos_para_consolidar"("p_plataforma_id" integer, "p_is_flex" boolean, "p_data_inicio" timestamp with time zone, "p_data_fim" timestamp with time zone, "p_search" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_pedidos_para_consolidar"("p_plataforma_id" integer, "p_is_flex" boolean, "p_data_inicio" timestamp with time zone, "p_data_fim" timestamp with time zone, "p_search" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_pedidos_por_demanda"("p_demanda_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."get_pedidos_por_demanda"("p_demanda_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_pedidos_por_demanda"("p_demanda_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_pedidos_similares"("p_pedido_id" integer, "p_limit" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."get_pedidos_similares"("p_pedido_id" integer, "p_limit" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_pedidos_similares"("p_pedido_id" integer, "p_limit" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_regras_consolidacao_canal"("p_canal_venda_id" bigint, "p_modalidade" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."get_regras_consolidacao_canal"("p_canal_venda_id" bigint, "p_modalidade" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_regras_consolidacao_canal"("p_canal_venda_id" bigint, "p_modalidade" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."grupo_bom_do_componente"("p_componente_id" integer, "p_grupo_linha" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."grupo_bom_do_componente"("p_componente_id" integer, "p_grupo_linha" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."grupo_bom_do_componente"("p_componente_id" integer, "p_grupo_linha" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."incrementar_batch_ia"("p_batch_id" "uuid", "p_sucesso" integer, "p_falha" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."incrementar_batch_ia"("p_batch_id" "uuid", "p_sucesso" integer, "p_falha" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."incrementar_batch_ia"("p_batch_id" "uuid", "p_sucesso" integer, "p_falha" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."item_snapshot_atributos"("p_item" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."item_snapshot_atributos"("p_item" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."item_snapshot_atributos"("p_item" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."itens_pedido_enriquecer"("p_pedido_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."itens_pedido_enriquecer"("p_pedido_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."itens_pedido_enriquecer"("p_pedido_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."janelas_despacho_vencidas"("p_agora" timestamp with time zone, "p_desde" interval) TO "anon";
GRANT ALL ON FUNCTION "public"."janelas_despacho_vencidas"("p_agora" timestamp with time zone, "p_desde" interval) TO "authenticated";
GRANT ALL ON FUNCTION "public"."janelas_despacho_vencidas"("p_agora" timestamp with time zone, "p_desde" interval) TO "service_role";



GRANT ALL ON FUNCTION "public"."janelas_logisticas"("p_modalidade_id" integer, "p_integration_id" integer, "p_dia" "date") TO "anon";
GRANT ALL ON FUNCTION "public"."janelas_logisticas"("p_modalidade_id" integer, "p_integration_id" integer, "p_dia" "date") TO "authenticated";
GRANT ALL ON FUNCTION "public"."janelas_logisticas"("p_modalidade_id" integer, "p_integration_id" integer, "p_dia" "date") TO "service_role";



GRANT ALL ON FUNCTION "public"."list_pedidos_filtrados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_sort" "text", "p_order" "text", "p_limit" integer, "p_offset" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."list_pedidos_filtrados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_sort" "text", "p_order" "text", "p_limit" integer, "p_offset" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."list_pedidos_filtrados"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_sort" "text", "p_order" "text", "p_limit" integer, "p_offset" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."list_pedidos_filtrados_v2"("p_limit" integer, "p_offset" integer, "p_sort" "text", "p_order" "text", "p_origem_pedido_key" "text", "p_situacao_pedido_id" integer, "p_bling_integration_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_delivery_start_date" timestamp without time zone, "p_delivery_end_date" timestamp without time zone, "p_pedido_date_start" "date", "p_pedido_date_end" "date", "p_search_term" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."list_pedidos_filtrados_v2"("p_limit" integer, "p_offset" integer, "p_sort" "text", "p_order" "text", "p_origem_pedido_key" "text", "p_situacao_pedido_id" integer, "p_bling_integration_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_delivery_start_date" timestamp without time zone, "p_delivery_end_date" timestamp without time zone, "p_pedido_date_start" "date", "p_pedido_date_end" "date", "p_search_term" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."list_pedidos_filtrados_v2"("p_limit" integer, "p_offset" integer, "p_sort" "text", "p_order" "text", "p_origem_pedido_key" "text", "p_situacao_pedido_id" integer, "p_bling_integration_id" integer, "p_canal_venda_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_delivery_start_date" timestamp without time zone, "p_delivery_end_date" timestamp without time zone, "p_pedido_date_start" "date", "p_pedido_date_end" "date", "p_search_term" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."list_pedidos_por_compra"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."list_pedidos_por_compra"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."list_pedidos_por_compra"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."list_pedidos_por_compra"("p_situacao_pedido_id" integer, "p_canal_venda_id" integer, "p_origem_pedido_key" "text", "p_bling_integration_id" integer, "p_has_demanda" boolean, "p_is_flex" boolean, "p_is_personalizado" boolean, "p_is_fulfillment" boolean, "p_delivery_start_date" "text", "p_delivery_end_date" "text", "p_pedido_date_start" "text", "p_pedido_date_end" "text", "p_search_term" "text", "p_limit" integer, "p_offset" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."listar_produtos_prontidao"("p_tag_id" integer, "p_estagio" "public"."estagio_produto") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."listar_produtos_prontidao"("p_tag_id" integer, "p_estagio" "public"."estagio_produto") TO "authenticated";
GRANT ALL ON FUNCTION "public"."listar_produtos_prontidao"("p_tag_id" integer, "p_estagio" "public"."estagio_produto") TO "service_role";



GRANT ALL ON FUNCTION "public"."manutencao_desfazer_lote"("p_lote" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."manutencao_desfazer_lote"("p_lote" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."manutencao_desfazer_lote"("p_lote" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."manutencao_marcar_entregues_ate"("p_data" "date", "p_dry_run" boolean, "p_executado_por" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."manutencao_marcar_entregues_ate"("p_data" "date", "p_dry_run" boolean, "p_executado_por" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."manutencao_marcar_entregues_ate"("p_data" "date", "p_dry_run" boolean, "p_executado_por" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."marcar_alocacao_processada"("p_correlation_id" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."marcar_alocacao_processada"("p_correlation_id" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."marcar_alocacao_processada"("p_correlation_id" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."miolo_do_sku"("p_sku" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."miolo_do_sku"("p_sku" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."miolo_do_sku"("p_sku" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."normalize_text_for_flex"("input_text" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."normalize_text_for_flex"("input_text" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."normalize_text_for_flex"("input_text" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."pedidos_pacotes"("p_pedido_ids" bigint[]) TO "anon";
GRANT ALL ON FUNCTION "public"."pedidos_pacotes"("p_pedido_ids" bigint[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."pedidos_pacotes"("p_pedido_ids" bigint[]) TO "service_role";



REVOKE ALL ON FUNCTION "public"."process_marketplace_order_effect"("p_effect_id" bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."process_marketplace_order_effect"("p_effect_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."process_marketplace_order_effect"("p_effect_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."process_marketplace_order_effect"("p_effect_id" bigint) TO "service_role";



REVOKE ALL ON FUNCTION "public"."produto_prontidao"("p_produto_id" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."produto_prontidao"("p_produto_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."produto_prontidao"("p_produto_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."proxima_janela_logistica"("p_modalidade_id" integer, "p_integration_id" integer, "p_agora" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."proxima_janela_logistica"("p_modalidade_id" integer, "p_integration_id" integer, "p_agora" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."proxima_janela_logistica"("p_modalidade_id" integer, "p_integration_id" integer, "p_agora" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."public_merchant_store"("_merchant_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."public_merchant_store"("_merchant_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."public_merchant_store"("_merchant_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."validar_gtin"("p_gtin" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."validar_gtin"("p_gtin" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."validar_gtin"("p_gtin" "text") TO "service_role";



GRANT ALL ON TABLE "public"."produtos" TO "anon";
GRANT ALL ON TABLE "public"."produtos" TO "authenticated";
GRANT ALL ON TABLE "public"."produtos" TO "service_role";



REVOKE ALL ON FUNCTION "public"."publicar_produto"("p_produto_id" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."publicar_produto"("p_produto_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."publicar_produto"("p_produto_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."purgar_logs_retencao"() TO "anon";
GRANT ALL ON FUNCTION "public"."purgar_logs_retencao"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."purgar_logs_retencao"() TO "service_role";



GRANT ALL ON FUNCTION "public"."purgar_logs_retencao"("p_lote" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."purgar_logs_retencao"("p_lote" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."purgar_logs_retencao"("p_lote" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."reclassificar_modalidade_backlog"("p_limite" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."reclassificar_modalidade_backlog"("p_limite" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."reclassificar_modalidade_backlog"("p_limite" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."reconciliar_item_estoque"("p_item_id" integer, "p_demanda_id" integer, "p_movimentos" "jsonb", "p_snapshot" "jsonb", "p_correlation_id" "uuid", "p_user_id" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."reconciliar_item_estoque"("p_item_id" integer, "p_demanda_id" integer, "p_movimentos" "jsonb", "p_snapshot" "jsonb", "p_correlation_id" "uuid", "p_user_id" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."reconciliar_item_estoque"("p_item_id" integer, "p_demanda_id" integer, "p_movimentos" "jsonb", "p_snapshot" "jsonb", "p_correlation_id" "uuid", "p_user_id" character varying) TO "service_role";



REVOKE ALL ON FUNCTION "public"."registrar_alteracao_sku"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."registrar_alteracao_sku"() TO "service_role";



GRANT ALL ON FUNCTION "public"."registrar_metodo_envio_observado"("p_module_id" character varying, "p_integration_id" integer, "p_campo_origem" character varying, "p_chave" "text", "p_rotulo" "text", "p_pedido_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."registrar_metodo_envio_observado"("p_module_id" character varying, "p_integration_id" integer, "p_campo_origem" character varying, "p_chave" "text", "p_rotulo" "text", "p_pedido_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."registrar_metodo_envio_observado"("p_module_id" character varying, "p_integration_id" integer, "p_campo_origem" character varying, "p_chave" "text", "p_rotulo" "text", "p_pedido_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."registrar_movimentacao_primaria"("p_produto_id" integer, "p_deposito_id" integer, "p_tipo_movimentacao" character varying, "p_quantidade" numeric, "p_motivo" "text", "p_origem_tipo" integer, "p_usuario_id" integer, "p_documento_referencia" character varying, "p_correlation_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."registrar_movimentacao_primaria"("p_produto_id" integer, "p_deposito_id" integer, "p_tipo_movimentacao" character varying, "p_quantidade" numeric, "p_motivo" "text", "p_origem_tipo" integer, "p_usuario_id" integer, "p_documento_referencia" character varying, "p_correlation_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."registrar_movimentacao_primaria"("p_produto_id" integer, "p_deposito_id" integer, "p_tipo_movimentacao" character varying, "p_quantidade" numeric, "p_motivo" "text", "p_origem_tipo" integer, "p_usuario_id" integer, "p_documento_referencia" character varying, "p_correlation_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."registrar_saida_coleta_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."registrar_saida_coleta_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."registrar_saida_coleta_demanda"("p_demanda_id" integer, "p_user_id" "text") TO "service_role";



GRANT ALL ON TABLE "public"."regras_logisticas_integracao" TO "anon";
GRANT ALL ON TABLE "public"."regras_logisticas_integracao" TO "authenticated";
GRANT ALL ON TABLE "public"."regras_logisticas_integracao" TO "service_role";



GRANT ALL ON FUNCTION "public"."regras_da_modalidade"("p_modalidade_id" integer, "p_integration_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."regras_da_modalidade"("p_modalidade_id" integer, "p_integration_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."regras_da_modalidade"("p_modalidade_id" integer, "p_integration_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."repair_personalized_classification"("p_pedido_ids" bigint[], "p_source" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."repair_personalized_classification"("p_pedido_ids" bigint[], "p_source" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."repair_personalized_classification"("p_pedido_ids" bigint[], "p_source" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."resolver_compromisso_logistico"("p_modalidade_id" integer, "p_integration_id" integer, "p_data_venda" timestamp with time zone, "p_agora" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."resolver_compromisso_logistico"("p_modalidade_id" integer, "p_integration_id" integer, "p_data_venda" timestamp with time zone, "p_agora" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."resolver_compromisso_logistico"("p_modalidade_id" integer, "p_integration_id" integer, "p_data_venda" timestamp with time zone, "p_agora" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text", "p_usar_fallback" boolean, OUT "miolo_id" integer, OUT "origem" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text", "p_usar_fallback" boolean, OUT "miolo_id" integer, OUT "origem" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."resolver_miolo_por_prefixo"("p_codigo" "text", "p_plataforma" "text", "p_usar_fallback" boolean, OUT "miolo_id" integer, OUT "origem" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."resolver_produto_completo"("p_codigo" "text", "p_plataforma" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."resolver_produto_completo"("p_codigo" "text", "p_plataforma" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."resolver_produto_completo"("p_codigo" "text", "p_plataforma" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."resolver_produto_por_codigo"("p_codigo" "text", "p_plataforma" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."resolver_produto_por_codigo"("p_codigo" "text", "p_plataforma" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."resolver_produto_por_codigo"("p_codigo" "text", "p_plataforma" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."rollup_ingest_daily"("p_ate" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."rollup_ingest_daily"("p_ate" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."rollup_ingest_daily"("p_ate" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."rollup_task_daily"("p_ate" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."rollup_task_daily"("p_ate" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."rollup_task_daily"("p_ate" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."rollup_webhook_daily"("p_ate" timestamp with time zone) TO "anon";
GRANT ALL ON FUNCTION "public"."rollup_webhook_daily"("p_ate" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."rollup_webhook_daily"("p_ate" timestamp with time zone) TO "service_role";



GRANT ALL ON FUNCTION "public"."simular_reconciliacao_item"("p_item_id" integer, "p_quantidade" numeric) TO "anon";
GRANT ALL ON FUNCTION "public"."simular_reconciliacao_item"("p_item_id" integer, "p_quantidade" numeric) TO "authenticated";
GRANT ALL ON FUNCTION "public"."simular_reconciliacao_item"("p_item_id" integer, "p_quantidade" numeric) TO "service_role";



GRANT ALL ON FUNCTION "public"."sincronizar_tipo_produto"() TO "anon";
GRANT ALL ON FUNCTION "public"."sincronizar_tipo_produto"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."sincronizar_tipo_produto"() TO "service_role";



GRANT ALL ON FUNCTION "public"."snapshot_estoque_item"("p_item_id" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."snapshot_estoque_item"("p_item_id" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."snapshot_estoque_item"("p_item_id" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."standardize_table_timestamps"("target_table" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."standardize_table_timestamps"("target_table" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."standardize_table_timestamps"("target_table" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."sync_canonical_order_compat_fields"() TO "anon";
GRANT ALL ON FUNCTION "public"."sync_canonical_order_compat_fields"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."sync_canonical_order_compat_fields"() TO "service_role";



GRANT ALL ON FUNCTION "public"."sync_marketplace_snapshot_items"() TO "anon";
GRANT ALL ON FUNCTION "public"."sync_marketplace_snapshot_items"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."sync_marketplace_snapshot_items"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_item_pedido_enriquece"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_item_pedido_enriquece"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_item_pedido_enriquece"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_pedido_classifica_modalidade"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_pedido_classifica_modalidade"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_pedido_classifica_modalidade"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_pedidos_sync_is_flex"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_pedidos_sync_is_flex"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_pedidos_sync_is_flex"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_regra_logistica_sync_modalidade"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_regra_logistica_sync_modalidade"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_regra_logistica_sync_modalidade"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_regra_sincroniza_modalidade_principal"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_regra_sincroniza_modalidade_principal"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_regra_sincroniza_modalidade_principal"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_snapshot_classifica_modalidade"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_snapshot_classifica_modalidade"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_snapshot_classifica_modalidade"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_snapshot_enriquece_itens"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_snapshot_enriquece_itens"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_snapshot_enriquece_itens"() TO "service_role";



GRANT ALL ON FUNCTION "public"."tg_touch_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."tg_touch_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."tg_touch_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."trg_demandas_pedidos_sincroniza_carimbo"() TO "anon";
GRANT ALL ON FUNCTION "public"."trg_demandas_pedidos_sincroniza_carimbo"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."trg_demandas_pedidos_sincroniza_carimbo"() TO "service_role";



GRANT ALL ON FUNCTION "public"."trg_demandas_producao_sincroniza_carimbo"() TO "anon";
GRANT ALL ON FUNCTION "public"."trg_demandas_producao_sincroniza_carimbo"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."trg_demandas_producao_sincroniza_carimbo"() TO "service_role";



GRANT ALL ON FUNCTION "public"."truncate_if_exists"("p_table" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."truncate_if_exists"("p_table" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."truncate_if_exists"("p_table" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."update_alertas_demanda_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_alertas_demanda_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_alertas_demanda_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_consolidacoes_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_consolidacoes_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_consolidacoes_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_modified_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_modified_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_modified_column"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_produtos_updated_at_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_produtos_updated_at_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_produtos_updated_at_column"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."upsert_canonical_order"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."upsert_canonical_order"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."upsert_canonical_order"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."upsert_canonical_order"("p_order" "jsonb", "p_snapshot" "jsonb", "p_refs" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."validar_componente_ficha_tecnica"() TO "anon";
GRANT ALL ON FUNCTION "public"."validar_componente_ficha_tecnica"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."validar_componente_ficha_tecnica"() TO "service_role";



GRANT ALL ON FUNCTION "public"."validar_componente_kit"() TO "anon";
GRANT ALL ON FUNCTION "public"."validar_componente_kit"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."validar_componente_kit"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."validar_preco_produto"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."validar_preco_produto"() TO "service_role";



GRANT ALL ON FUNCTION "public"."validar_tipo_produto_variacao"() TO "anon";
GRANT ALL ON FUNCTION "public"."validar_tipo_produto_variacao"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."validar_tipo_produto_variacao"() TO "service_role";



GRANT ALL ON FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."verificar_alocacao_existente"("p_correlation_id" character varying) TO "service_role";



GRANT ALL ON TABLE "public"."agenda_recursos" TO "anon";
GRANT ALL ON TABLE "public"."agenda_recursos" TO "authenticated";
GRANT ALL ON TABLE "public"."agenda_recursos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."agenda_recursos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."agenda_recursos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."agenda_recursos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."logs_execucao_ia" TO "anon";
GRANT ALL ON TABLE "public"."logs_execucao_ia" TO "authenticated";
GRANT ALL ON TABLE "public"."logs_execucao_ia" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ai_execution_logs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ai_execution_logs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ai_execution_logs_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."alertas_demanda" TO "anon";
GRANT ALL ON TABLE "public"."alertas_demanda" TO "authenticated";
GRANT ALL ON TABLE "public"."alertas_demanda" TO "service_role";



GRANT ALL ON SEQUENCE "public"."alertas_demanda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."alertas_demanda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."alertas_demanda_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."archive_manifests" TO "service_role";



GRANT ALL ON SEQUENCE "public"."archive_manifests_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."archive_manifests_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."archive_manifests_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."cache_dashboard_pedidos" TO "anon";
GRANT ALL ON TABLE "public"."cache_dashboard_pedidos" TO "authenticated";
GRANT ALL ON TABLE "public"."cache_dashboard_pedidos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."canais_venda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."canais_venda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."canais_venda_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."canal_modalidade_mapeamento" TO "anon";
GRANT ALL ON TABLE "public"."canal_modalidade_mapeamento" TO "authenticated";
GRANT ALL ON TABLE "public"."canal_modalidade_mapeamento" TO "service_role";



GRANT ALL ON SEQUENCE "public"."canal_modalidade_mapeamento_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."canal_modalidade_mapeamento_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."canal_modalidade_mapeamento_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."categoria_bom_regras" TO "anon";
GRANT ALL ON TABLE "public"."categoria_bom_regras" TO "authenticated";
GRANT ALL ON TABLE "public"."categoria_bom_regras" TO "service_role";



GRANT ALL ON SEQUENCE "public"."categoria_bom_regras_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."categoria_bom_regras_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."categoria_bom_regras_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."categorias" TO "anon";
GRANT ALL ON TABLE "public"."categorias" TO "authenticated";
GRANT ALL ON TABLE "public"."categorias" TO "service_role";



GRANT ALL ON SEQUENCE "public"."categorias_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."categorias_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."categorias_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."channel_connections" TO "anon";
GRANT ALL ON TABLE "public"."channel_connections" TO "authenticated";
GRANT ALL ON TABLE "public"."channel_connections" TO "service_role";



GRANT ALL ON TABLE "public"."componentes_ordem_producao" TO "anon";
GRANT ALL ON TABLE "public"."componentes_ordem_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."componentes_ordem_producao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."componentes_ordem_producao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."componentes_ordem_producao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."componentes_ordem_producao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."conferencias_arquivo" TO "anon";
GRANT ALL ON TABLE "public"."conferencias_arquivo" TO "authenticated";
GRANT ALL ON TABLE "public"."conferencias_arquivo" TO "service_role";



GRANT ALL ON SEQUENCE "public"."conferencias_arquivo_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."conferencias_arquivo_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."conferencias_arquivo_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."configuracoes_aplicacao" TO "anon";
GRANT ALL ON TABLE "public"."configuracoes_aplicacao" TO "authenticated";
GRANT ALL ON TABLE "public"."configuracoes_aplicacao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."configuracoes_aplicacao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."configuracoes_aplicacao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."configuracoes_aplicacao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."consolidacoes_pedido" TO "anon";
GRANT ALL ON TABLE "public"."consolidacoes_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."consolidacoes_pedido" TO "service_role";



GRANT ALL ON SEQUENCE "public"."consolidacoes_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."consolidacoes_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."consolidacoes_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."contas_bling" TO "anon";
GRANT ALL ON TABLE "public"."contas_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."contas_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."contas_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."contas_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."contas_bling_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."contextos_producao" TO "anon";
GRANT ALL ON TABLE "public"."contextos_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."contextos_producao" TO "service_role";



GRANT ALL ON TABLE "public"."conversoes_uom_produto" TO "anon";
GRANT ALL ON TABLE "public"."conversoes_uom_produto" TO "authenticated";
GRANT ALL ON TABLE "public"."conversoes_uom_produto" TO "service_role";



GRANT ALL ON SEQUENCE "public"."conversoes_uom_produto_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."conversoes_uom_produto_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."conversoes_uom_produto_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."demanda_alocacoes_estoque" TO "anon";
GRANT ALL ON TABLE "public"."demanda_alocacoes_estoque" TO "authenticated";
GRANT ALL ON TABLE "public"."demanda_alocacoes_estoque" TO "service_role";



GRANT ALL ON TABLE "public"."demanda_estoque_processado" TO "anon";
GRANT ALL ON TABLE "public"."demanda_estoque_processado" TO "authenticated";
GRANT ALL ON TABLE "public"."demanda_estoque_processado" TO "service_role";



GRANT ALL ON TABLE "public"."demandas_item_origem" TO "anon";
GRANT ALL ON TABLE "public"."demandas_item_origem" TO "authenticated";
GRANT ALL ON TABLE "public"."demandas_item_origem" TO "service_role";



GRANT ALL ON SEQUENCE "public"."demandas_item_origem_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."demandas_item_origem_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."demandas_item_origem_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."demandas_overrides" TO "anon";
GRANT ALL ON TABLE "public"."demandas_overrides" TO "authenticated";
GRANT ALL ON TABLE "public"."demandas_overrides" TO "service_role";



GRANT ALL ON SEQUENCE "public"."demandas_overrides_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."demandas_overrides_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."demandas_overrides_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."demandas_pedidos" TO "anon";
GRANT ALL ON TABLE "public"."demandas_pedidos" TO "authenticated";
GRANT ALL ON TABLE "public"."demandas_pedidos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."demandas_pedidos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."demandas_pedidos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."demandas_pedidos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."demandas_producao" TO "anon";
GRANT ALL ON TABLE "public"."demandas_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."demandas_producao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."demandas_producao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."demandas_producao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."demandas_producao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."depositos" TO "anon";
GRANT ALL ON TABLE "public"."depositos" TO "authenticated";
GRANT ALL ON TABLE "public"."depositos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."depositos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."depositos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."depositos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."metodos_envio_observados" TO "anon";
GRANT ALL ON TABLE "public"."metodos_envio_observados" TO "authenticated";
GRANT ALL ON TABLE "public"."metodos_envio_observados" TO "service_role";



GRANT ALL ON TABLE "public"."modalidades_logisticas" TO "anon";
GRANT ALL ON TABLE "public"."modalidades_logisticas" TO "authenticated";
GRANT ALL ON TABLE "public"."modalidades_logisticas" TO "service_role";



GRANT ALL ON TABLE "public"."regras_classificacao_modalidade" TO "anon";
GRANT ALL ON TABLE "public"."regras_classificacao_modalidade" TO "authenticated";
GRANT ALL ON TABLE "public"."regras_classificacao_modalidade" TO "service_role";



GRANT ALL ON TABLE "public"."divergencias_regra_canal" TO "anon";
GRANT ALL ON TABLE "public"."divergencias_regra_canal" TO "authenticated";
GRANT ALL ON TABLE "public"."divergencias_regra_canal" TO "service_role";



GRANT ALL ON TABLE "public"."entity_correlation_mapping" TO "anon";
GRANT ALL ON TABLE "public"."entity_correlation_mapping" TO "authenticated";
GRANT ALL ON TABLE "public"."entity_correlation_mapping" TO "service_role";



GRANT ALL ON TABLE "public"."entrega_producao" TO "anon";
GRANT ALL ON TABLE "public"."entrega_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."entrega_producao" TO "service_role";



GRANT ALL ON TABLE "public"."erp_marketplace_links" TO "anon";
GRANT ALL ON TABLE "public"."erp_marketplace_links" TO "authenticated";
GRANT ALL ON TABLE "public"."erp_marketplace_links" TO "service_role";



GRANT ALL ON TABLE "public"."estoque_atual" TO "anon";
GRANT ALL ON TABLE "public"."estoque_atual" TO "authenticated";
GRANT ALL ON TABLE "public"."estoque_atual" TO "service_role";



GRANT ALL ON SEQUENCE "public"."estoque_atual_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."estoque_atual_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."estoque_atual_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."eventos_auditoria" TO "anon";
GRANT ALL ON TABLE "public"."eventos_auditoria" TO "authenticated";
GRANT ALL ON TABLE "public"."eventos_auditoria" TO "service_role";



GRANT ALL ON SEQUENCE "public"."eventos_auditoria_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."eventos_auditoria_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."eventos_auditoria_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."eventos_pedido" TO "anon";
GRANT ALL ON TABLE "public"."eventos_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."eventos_pedido" TO "service_role";



GRANT ALL ON TABLE "public"."eventos_producao_v2" TO "anon";
GRANT ALL ON TABLE "public"."eventos_producao_v2" TO "authenticated";
GRANT ALL ON TABLE "public"."eventos_producao_v2" TO "service_role";



GRANT ALL ON TABLE "public"."execucoes_ai_batch" TO "anon";
GRANT ALL ON TABLE "public"."execucoes_ai_batch" TO "authenticated";
GRANT ALL ON TABLE "public"."execucoes_ai_batch" TO "service_role";



GRANT ALL ON TABLE "public"."execucoes_ai_item" TO "anon";
GRANT ALL ON TABLE "public"."execucoes_ai_item" TO "authenticated";
GRANT ALL ON TABLE "public"."execucoes_ai_item" TO "service_role";



GRANT ALL ON SEQUENCE "public"."execucoes_ai_item_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."execucoes_ai_item_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."execucoes_ai_item_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."feedback_pedido" TO "anon";
GRANT ALL ON TABLE "public"."feedback_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."feedback_pedido" TO "service_role";



GRANT ALL ON SEQUENCE "public"."feedback_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."feedback_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."feedback_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."ficha_tecnica" TO "anon";
GRANT ALL ON TABLE "public"."ficha_tecnica" TO "authenticated";
GRANT ALL ON TABLE "public"."ficha_tecnica" TO "service_role";



GRANT ALL ON TABLE "public"."ficha_tecnica_classificacao_pendente" TO "anon";
GRANT ALL ON TABLE "public"."ficha_tecnica_classificacao_pendente" TO "authenticated";
GRANT ALL ON TABLE "public"."ficha_tecnica_classificacao_pendente" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ficha_tecnica_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ficha_tecnica_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ficha_tecnica_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."fornecedor_insumos" TO "anon";
GRANT ALL ON TABLE "public"."fornecedor_insumos" TO "authenticated";
GRANT ALL ON TABLE "public"."fornecedor_insumos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."fornecedor_insumos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."fornecedor_insumos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."fornecedor_insumos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."fornecedores" TO "anon";
GRANT ALL ON TABLE "public"."fornecedores" TO "authenticated";
GRANT ALL ON TABLE "public"."fornecedores" TO "service_role";



GRANT ALL ON SEQUENCE "public"."fornecedores_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."fornecedores_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."fornecedores_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."grupo_mensagens_chat_shopee" TO "anon";
GRANT ALL ON TABLE "public"."grupo_mensagens_chat_shopee" TO "authenticated";
GRANT ALL ON TABLE "public"."grupo_mensagens_chat_shopee" TO "service_role";



GRANT ALL ON TABLE "public"."ingest_daily_stats" TO "anon";
GRANT ALL ON TABLE "public"."ingest_daily_stats" TO "authenticated";
GRANT ALL ON TABLE "public"."ingest_daily_stats" TO "service_role";



GRANT ALL ON SEQUENCE "public"."installed_integrations_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."installed_integrations_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."installed_integrations_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."integracao_canais_config" TO "anon";
GRANT ALL ON TABLE "public"."integracao_canais_config" TO "authenticated";
GRANT ALL ON TABLE "public"."integracao_canais_config" TO "service_role";



GRANT ALL ON TABLE "public"."integration_account_routing" TO "anon";
GRANT ALL ON TABLE "public"."integration_account_routing" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_account_routing" TO "service_role";



GRANT ALL ON TABLE "public"."integration_app_profiles" TO "service_role";



GRANT ALL ON SEQUENCE "public"."integration_app_profiles_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."integration_app_profiles_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."integration_app_profiles_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."integration_mapping_rules" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_mapping_rules" TO "service_role";



GRANT ALL ON SEQUENCE "public"."integration_mapping_rules_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."integration_mapping_rules_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."integration_mapping_rules_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."integration_modules" TO "anon";
GRANT ALL ON TABLE "public"."integration_modules" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_modules" TO "service_role";



GRANT ALL ON TABLE "public"."integration_refresh_logs" TO "anon";
GRANT ALL ON TABLE "public"."integration_refresh_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_refresh_logs" TO "service_role";



GRANT ALL ON SEQUENCE "public"."integration_refresh_logs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."integration_refresh_logs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."integration_refresh_logs_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."integration_secret_values" TO "service_role";



GRANT ALL ON SEQUENCE "public"."integration_secret_values_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."integration_secret_values_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."integration_secret_values_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."integration_status_mappings" TO "anon";
GRANT ALL ON TABLE "public"."integration_status_mappings" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_status_mappings" TO "service_role";



GRANT ALL ON SEQUENCE "public"."integration_status_mappings_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."integration_status_mappings_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."integration_status_mappings_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."itens_demanda" TO "anon";
GRANT ALL ON TABLE "public"."itens_demanda" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_demanda" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_demanda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_demanda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_demanda_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."itens_ordem_compra" TO "anon";
GRANT ALL ON TABLE "public"."itens_ordem_compra" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_ordem_compra" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_ordem_compra_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_ordem_compra_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_ordem_compra_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."itens_pedido_bling" TO "anon";
GRANT ALL ON TABLE "public"."itens_pedido_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_pedido_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_pedido_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_pedido_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_pedido_bling_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."janelas_despacho_execucoes" TO "anon";
GRANT ALL ON TABLE "public"."janelas_despacho_execucoes" TO "authenticated";
GRANT ALL ON TABLE "public"."janelas_despacho_execucoes" TO "service_role";



GRANT ALL ON SEQUENCE "public"."janelas_despacho_execucoes_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."janelas_despacho_execucoes_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."janelas_despacho_execucoes_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."logs_producao_diaria" TO "anon";
GRANT ALL ON TABLE "public"."logs_producao_diaria" TO "authenticated";
GRANT ALL ON TABLE "public"."logs_producao_diaria" TO "service_role";



GRANT ALL ON SEQUENCE "public"."logs_producao_diaria_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."logs_producao_diaria_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."logs_producao_diaria_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."manutencao_status_log" TO "anon";
GRANT ALL ON TABLE "public"."manutencao_status_log" TO "authenticated";
GRANT ALL ON TABLE "public"."manutencao_status_log" TO "service_role";



GRANT ALL ON SEQUENCE "public"."manutencao_status_log_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."manutencao_status_log_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."manutencao_status_log_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."marketplace_order_effects" TO "service_role";



GRANT ALL ON SEQUENCE "public"."marketplace_order_effects_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."marketplace_order_effects_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."marketplace_order_effects_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."marketplace_order_transitions" TO "service_role";



GRANT ALL ON SEQUENCE "public"."marketplace_order_transitions_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."marketplace_order_transitions_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."marketplace_order_transitions_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."mensagem_chat_shopee" TO "service_role";
GRANT SELECT ON TABLE "public"."mensagem_chat_shopee" TO "authenticated";



GRANT ALL ON SEQUENCE "public"."metodos_envio_observados_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."metodos_envio_observados_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."metodos_envio_observados_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."modalidades_logisticas_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."modalidades_logisticas_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."modalidades_logisticas_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."movimentacoes_estoque" TO "anon";
GRANT ALL ON TABLE "public"."movimentacoes_estoque" TO "authenticated";
GRANT ALL ON TABLE "public"."movimentacoes_estoque" TO "service_role";



GRANT ALL ON SEQUENCE "public"."movimentacoes_estoque_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."movimentacoes_estoque_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."movimentacoes_estoque_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."notificacoes" TO "anon";
GRANT ALL ON TABLE "public"."notificacoes" TO "authenticated";
GRANT ALL ON TABLE "public"."notificacoes" TO "service_role";



GRANT ALL ON SEQUENCE "public"."notificacoes_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."notificacoes_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."notificacoes_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."oauth_authorization_sessions" TO "service_role";



GRANT ALL ON SEQUENCE "public"."oauth_authorization_sessions_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."oauth_authorization_sessions_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."oauth_authorization_sessions_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."ordens_compra" TO "anon";
GRANT ALL ON TABLE "public"."ordens_compra" TO "authenticated";
GRANT ALL ON TABLE "public"."ordens_compra" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ordens_compra_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ordens_compra_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ordens_compra_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."ordens_producao" TO "anon";
GRANT ALL ON TABLE "public"."ordens_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."ordens_producao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ordens_producao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ordens_producao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ordens_producao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."order_identity_corrections" TO "service_role";



GRANT ALL ON SEQUENCE "public"."order_identity_corrections_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."order_identity_corrections_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."order_identity_corrections_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedido_ingest_log" TO "anon";
GRANT ALL ON TABLE "public"."pedido_ingest_log" TO "authenticated";
GRANT ALL ON TABLE "public"."pedido_ingest_log" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedido_ingest_log_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedido_ingest_log_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedido_ingest_log_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedido_integration_refs" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedido_integration_refs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedido_integration_refs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedido_integration_refs_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedido_snapshots" TO "anon";
GRANT ALL ON TABLE "public"."pedido_snapshots" TO "authenticated";
GRANT ALL ON TABLE "public"."pedido_snapshots" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedido_snapshots_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedido_snapshots_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedido_snapshots_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos_bling" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_bling_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos_com_external_id" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_com_external_id" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_com_external_id" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos_mercadolivre" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_mercadolivre" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_mercadolivre" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_mercadolivre_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_mercadolivre_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_mercadolivre_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos_nao_classificados" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_nao_classificados" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_nao_classificados" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_nao_classificados_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_nao_classificados_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_nao_classificados_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos_shopee" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_shopee" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_shopee" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_shopee_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_shopee_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_shopee_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pending_marketplace_enrichments" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pending_marketplace_enrichments_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pending_marketplace_enrichments_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pending_marketplace_enrichments_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pending_order_reconciliations" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pending_order_reconciliations_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pending_order_reconciliations_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pending_order_reconciliations_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."perfis_fiscais" TO "anon";
GRANT ALL ON TABLE "public"."perfis_fiscais" TO "authenticated";
GRANT ALL ON TABLE "public"."perfis_fiscais" TO "service_role";



GRANT ALL ON SEQUENCE "public"."perfis_fiscais_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."perfis_fiscais_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."perfis_fiscais_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."permissoes_setor" TO "anon";
GRANT ALL ON TABLE "public"."permissoes_setor" TO "authenticated";
GRANT ALL ON TABLE "public"."permissoes_setor" TO "service_role";



GRANT ALL ON SEQUENCE "public"."permissoes_setor_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."permissoes_setor_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."permissoes_setor_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."personalizacoes_pedido" TO "anon";
GRANT ALL ON TABLE "public"."personalizacoes_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."personalizacoes_pedido" TO "service_role";



GRANT ALL ON SEQUENCE "public"."personalizacoes_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."personalizacoes_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."personalizacoes_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."plataformas" TO "anon";
GRANT ALL ON TABLE "public"."plataformas" TO "authenticated";
GRANT ALL ON TABLE "public"."plataformas" TO "service_role";



GRANT ALL ON TABLE "public"."plataformas_compat" TO "anon";
GRANT ALL ON TABLE "public"."plataformas_compat" TO "authenticated";
GRANT ALL ON TABLE "public"."plataformas_compat" TO "service_role";



GRANT ALL ON SEQUENCE "public"."plataformas_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."plataformas_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."plataformas_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pontos_coleta" TO "anon";
GRANT ALL ON TABLE "public"."pontos_coleta" TO "authenticated";
GRANT ALL ON TABLE "public"."pontos_coleta" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pontos_coleta_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pontos_coleta_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pontos_coleta_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."preferencias_ux_usuario" TO "anon";
GRANT ALL ON TABLE "public"."preferencias_ux_usuario" TO "authenticated";
GRANT ALL ON TABLE "public"."preferencias_ux_usuario" TO "service_role";



GRANT ALL ON TABLE "public"."previsao_consumo_demanda" TO "anon";
GRANT ALL ON TABLE "public"."previsao_consumo_demanda" TO "authenticated";
GRANT ALL ON TABLE "public"."previsao_consumo_demanda" TO "service_role";



GRANT ALL ON TABLE "public"."produto_alias_conflitos" TO "anon";
GRANT ALL ON TABLE "public"."produto_alias_conflitos" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_alias_conflitos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produto_alias_conflitos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produto_alias_conflitos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produto_alias_conflitos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."produto_anuncios" TO "anon";
GRANT ALL ON TABLE "public"."produto_anuncios" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_anuncios" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produto_anuncios_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produto_anuncios_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produto_anuncios_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."produto_eixo_opcao_componentes" TO "anon";
GRANT ALL ON TABLE "public"."produto_eixo_opcao_componentes" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_eixo_opcao_componentes" TO "service_role";



GRANT ALL ON TABLE "public"."produto_eixo_opcoes" TO "anon";
GRANT ALL ON TABLE "public"."produto_eixo_opcoes" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_eixo_opcoes" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produto_eixo_opcoes_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produto_eixo_opcoes_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produto_eixo_opcoes_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."produto_eixos" TO "anon";
GRANT ALL ON TABLE "public"."produto_eixos" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_eixos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produto_eixos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produto_eixos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produto_eixos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."produto_pai_eixos" TO "anon";
GRANT ALL ON TABLE "public"."produto_pai_eixos" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_pai_eixos" TO "service_role";



GRANT ALL ON TABLE "public"."produto_precos" TO "anon";
GRANT ALL ON TABLE "public"."produto_precos" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_precos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produto_precos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produto_precos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produto_precos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."produto_sku_historico" TO "anon";
GRANT ALL ON TABLE "public"."produto_sku_historico" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_sku_historico" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produto_sku_historico_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produto_sku_historico_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produto_sku_historico_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."produto_tags" TO "anon";
GRANT ALL ON TABLE "public"."produto_tags" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_tags" TO "service_role";



GRANT ALL ON TABLE "public"."produto_variacao_backfill_revisao" TO "anon";
GRANT ALL ON TABLE "public"."produto_variacao_backfill_revisao" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_variacao_backfill_revisao" TO "service_role";



GRANT ALL ON TABLE "public"."produto_variacao_valores" TO "anon";
GRANT ALL ON TABLE "public"."produto_variacao_valores" TO "authenticated";
GRANT ALL ON TABLE "public"."produto_variacao_valores" TO "service_role";



GRANT ALL ON TABLE "public"."produtos_externos" TO "anon";
GRANT ALL ON TABLE "public"."produtos_externos" TO "authenticated";
GRANT ALL ON TABLE "public"."produtos_externos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produtos_externos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produtos_externos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produtos_externos_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produtos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produtos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produtos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."recursos" TO "anon";
GRANT ALL ON TABLE "public"."recursos" TO "authenticated";
GRANT ALL ON TABLE "public"."recursos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."recursos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."recursos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."recursos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."recursos_produtivos" TO "anon";
GRANT ALL ON TABLE "public"."recursos_produtivos" TO "authenticated";
GRANT ALL ON TABLE "public"."recursos_produtivos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."recursos_produtivos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."recursos_produtivos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."recursos_produtivos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."regra_logistica_modalidades" TO "anon";
GRANT ALL ON TABLE "public"."regra_logistica_modalidades" TO "authenticated";
GRANT ALL ON TABLE "public"."regra_logistica_modalidades" TO "service_role";



GRANT ALL ON SEQUENCE "public"."regras_classificacao_modalidade_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."regras_classificacao_modalidade_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."regras_classificacao_modalidade_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."regras_consolidacao_canal" TO "anon";
GRANT ALL ON TABLE "public"."regras_consolidacao_canal" TO "authenticated";
GRANT ALL ON TABLE "public"."regras_consolidacao_canal" TO "service_role";



GRANT ALL ON SEQUENCE "public"."regras_consolidacao_canal_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."regras_consolidacao_canal_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."regras_consolidacao_canal_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."regras_logisticas_canal" TO "anon";
GRANT ALL ON TABLE "public"."regras_logisticas_canal" TO "authenticated";
GRANT ALL ON TABLE "public"."regras_logisticas_canal" TO "service_role";



GRANT ALL ON SEQUENCE "public"."regras_logisticas_canal_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."regras_logisticas_canal_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."regras_logisticas_canal_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."regras_logisticas_integracao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."regras_logisticas_integracao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."regras_logisticas_integracao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."regras_priorizacao" TO "anon";
GRANT ALL ON TABLE "public"."regras_priorizacao" TO "authenticated";
GRANT ALL ON TABLE "public"."regras_priorizacao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."regras_priorizacao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."regras_priorizacao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."regras_priorizacao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."setores" TO "anon";
GRANT ALL ON TABLE "public"."setores" TO "authenticated";
GRANT ALL ON TABLE "public"."setores" TO "service_role";



GRANT ALL ON SEQUENCE "public"."setores_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."setores_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."setores_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."sinalizacoes_demanda" TO "anon";
GRANT ALL ON TABLE "public"."sinalizacoes_demanda" TO "authenticated";
GRANT ALL ON TABLE "public"."sinalizacoes_demanda" TO "service_role";



GRANT ALL ON SEQUENCE "public"."sinalizacoes_demanda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."sinalizacoes_demanda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."sinalizacoes_demanda_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."situacoes_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."situacoes_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."situacoes_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."sync_status_batches" TO "anon";
GRANT ALL ON TABLE "public"."sync_status_batches" TO "authenticated";
GRANT ALL ON TABLE "public"."sync_status_batches" TO "service_role";



GRANT ALL ON TABLE "public"."sync_status_errors" TO "anon";
GRANT ALL ON TABLE "public"."sync_status_errors" TO "authenticated";
GRANT ALL ON TABLE "public"."sync_status_errors" TO "service_role";



GRANT ALL ON SEQUENCE "public"."sync_status_errors_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."sync_status_errors_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."sync_status_errors_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."system_events_log" TO "anon";
GRANT ALL ON TABLE "public"."system_events_log" TO "authenticated";
GRANT ALL ON TABLE "public"."system_events_log" TO "service_role";



GRANT ALL ON TABLE "public"."tags" TO "anon";
GRANT ALL ON TABLE "public"."tags" TO "authenticated";
GRANT ALL ON TABLE "public"."tags" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tags_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tags_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tags_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."task_daily_stats" TO "anon";
GRANT ALL ON TABLE "public"."task_daily_stats" TO "authenticated";
GRANT ALL ON TABLE "public"."task_daily_stats" TO "service_role";



GRANT ALL ON TABLE "public"."task_execution_logs" TO "anon";
GRANT ALL ON TABLE "public"."task_execution_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."task_execution_logs" TO "service_role";



GRANT ALL ON TABLE "public"."templates_obs_canal" TO "anon";
GRANT ALL ON TABLE "public"."templates_obs_canal" TO "authenticated";
GRANT ALL ON TABLE "public"."templates_obs_canal" TO "service_role";



GRANT ALL ON SEQUENCE "public"."templates_obs_canal_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."templates_obs_canal_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."templates_obs_canal_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."transicoes_situacao" TO "anon";
GRANT ALL ON TABLE "public"."transicoes_situacao" TO "authenticated";
GRANT ALL ON TABLE "public"."transicoes_situacao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."transicoes_situacao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."transicoes_situacao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."transicoes_situacao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."unidades_medida" TO "anon";
GRANT ALL ON TABLE "public"."unidades_medida" TO "authenticated";
GRANT ALL ON TABLE "public"."unidades_medida" TO "service_role";



GRANT ALL ON SEQUENCE "public"."unidades_medida_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."unidades_medida_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."unidades_medida_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."usuarios" TO "anon";
GRANT ALL ON TABLE "public"."usuarios" TO "authenticated";
GRANT ALL ON TABLE "public"."usuarios" TO "service_role";



GRANT ALL ON SEQUENCE "public"."usuarios_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."usuarios_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."usuarios_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."v_auditoria_bom_componentes_invalidos" TO "anon";
GRANT ALL ON TABLE "public"."v_auditoria_bom_componentes_invalidos" TO "authenticated";
GRANT ALL ON TABLE "public"."v_auditoria_bom_componentes_invalidos" TO "service_role";



GRANT ALL ON TABLE "public"."v_auditoria_variacoes_tipo_divergente" TO "anon";
GRANT ALL ON TABLE "public"."v_auditoria_variacoes_tipo_divergente" TO "authenticated";
GRANT ALL ON TABLE "public"."v_auditoria_variacoes_tipo_divergente" TO "service_role";



GRANT ALL ON TABLE "public"."v_canais_coleta_dia" TO "anon";
GRANT ALL ON TABLE "public"."v_canais_coleta_dia" TO "authenticated";
GRANT ALL ON TABLE "public"."v_canais_coleta_dia" TO "service_role";



GRANT ALL ON TABLE "public"."v_candidatos_verificacao_estoque" TO "anon";
GRANT ALL ON TABLE "public"."v_candidatos_verificacao_estoque" TO "authenticated";
GRANT ALL ON TABLE "public"."v_candidatos_verificacao_estoque" TO "service_role";



GRANT ALL ON TABLE "public"."v_itens_demanda_mapeamento" TO "anon";
GRANT ALL ON TABLE "public"."v_itens_demanda_mapeamento" TO "authenticated";
GRANT ALL ON TABLE "public"."v_itens_demanda_mapeamento" TO "service_role";



GRANT ALL ON TABLE "public"."v_pedido_demanda_rastreamento" TO "anon";
GRANT ALL ON TABLE "public"."v_pedido_demanda_rastreamento" TO "authenticated";
GRANT ALL ON TABLE "public"."v_pedido_demanda_rastreamento" TO "service_role";



GRANT ALL ON TABLE "public"."view_alocacoes_por_demanda" TO "anon";
GRANT ALL ON TABLE "public"."view_alocacoes_por_demanda" TO "authenticated";
GRANT ALL ON TABLE "public"."view_alocacoes_por_demanda" TO "service_role";



GRANT ALL ON TABLE "public"."view_alocacoes_por_item" TO "anon";
GRANT ALL ON TABLE "public"."view_alocacoes_por_item" TO "authenticated";
GRANT ALL ON TABLE "public"."view_alocacoes_por_item" TO "service_role";



GRANT ALL ON TABLE "public"."view_auditoria_tipo_produto" TO "anon";
GRANT ALL ON TABLE "public"."view_auditoria_tipo_produto" TO "authenticated";
GRANT ALL ON TABLE "public"."view_auditoria_tipo_produto" TO "service_role";



GRANT ALL ON TABLE "public"."view_consolidado_previsao_materiais" TO "anon";
GRANT ALL ON TABLE "public"."view_consolidado_previsao_materiais" TO "authenticated";
GRANT ALL ON TABLE "public"."view_consolidado_previsao_materiais" TO "service_role";



GRANT ALL ON TABLE "public"."view_consolidado_producao" TO "anon";
GRANT ALL ON TABLE "public"."view_consolidado_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."view_consolidado_producao" TO "service_role";



GRANT ALL ON TABLE "public"."view_ledger_completo" TO "anon";
GRANT ALL ON TABLE "public"."view_ledger_completo" TO "authenticated";
GRANT ALL ON TABLE "public"."view_ledger_completo" TO "service_role";



GRANT ALL ON TABLE "public"."view_mensagens_chat" TO "anon";
GRANT ALL ON TABLE "public"."view_mensagens_chat" TO "authenticated";
GRANT ALL ON TABLE "public"."view_mensagens_chat" TO "service_role";



GRANT ALL ON TABLE "public"."view_mensagens_chat_ai" TO "service_role";



GRANT ALL ON TABLE "public"."view_mensagens_chat_ai_v2" TO "service_role";



GRANT ALL ON TABLE "public"."view_movimentacoes_consolidadas" TO "anon";
GRANT ALL ON TABLE "public"."view_movimentacoes_consolidadas" TO "authenticated";
GRANT ALL ON TABLE "public"."view_movimentacoes_consolidadas" TO "service_role";



GRANT ALL ON TABLE "public"."view_pedidos_personalizados_ai" TO "service_role";



GRANT ALL ON TABLE "public"."view_vendas_personalizadas" TO "anon";
GRANT ALL ON TABLE "public"."view_vendas_personalizadas" TO "authenticated";
GRANT ALL ON TABLE "public"."view_vendas_personalizadas" TO "service_role";



GRANT ALL ON TABLE "public"."view_vendas_personalizadas_v3" TO "service_role";



GRANT ALL ON TABLE "public"."vinculos_bling" TO "anon";
GRANT ALL ON TABLE "public"."vinculos_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."vinculos_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."vinculos_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."vinculos_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."vinculos_bling_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."vinculos_integracao_pedido" TO "anon";
GRANT ALL ON TABLE "public"."vinculos_integracao_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."vinculos_integracao_pedido" TO "service_role";



GRANT ALL ON TABLE "public"."vw_despacho_carimbo_inconsistente" TO "anon";
GRANT ALL ON TABLE "public"."vw_despacho_carimbo_inconsistente" TO "authenticated";
GRANT ALL ON TABLE "public"."vw_despacho_carimbo_inconsistente" TO "service_role";



GRANT ALL ON TABLE "public"."vw_pedidos_pendentes_despacho" TO "anon";
GRANT ALL ON TABLE "public"."vw_pedidos_pendentes_despacho" TO "authenticated";
GRANT ALL ON TABLE "public"."vw_pedidos_pendentes_despacho" TO "service_role";



GRANT ALL ON TABLE "public"."webhook_daily_stats" TO "anon";
GRANT ALL ON TABLE "public"."webhook_daily_stats" TO "authenticated";
GRANT ALL ON TABLE "public"."webhook_daily_stats" TO "service_role";



GRANT ALL ON TABLE "public"."webhook_event_attempts" TO "service_role";



GRANT ALL ON SEQUENCE "public"."webhook_event_attempts_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."webhook_events" TO "service_role";



GRANT ALL ON SEQUENCE "public"."webhook_events_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."webhook_logs" TO "anon";
GRANT ALL ON TABLE "public"."webhook_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."webhook_logs" TO "service_role";



GRANT ALL ON SEQUENCE "public"."webhook_logs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."webhook_logs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."webhook_logs_id_seq" TO "service_role";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";







