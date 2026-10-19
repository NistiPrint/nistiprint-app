-- Fast global order-number lookup without assembling each matching order through
-- several PostgREST requests. The projection is only used after its backfill.
CREATE INDEX IF NOT EXISTS shopee_personalization_read_model_numero_prefix_idx
    ON public.shopee_personalization_read_model (numero_pedido text_pattern_ops);
CREATE INDEX IF NOT EXISTS shopee_personalization_read_model_loja_prefix_idx
    ON public.shopee_personalization_read_model (numero_loja text_pattern_ops);
CREATE INDEX IF NOT EXISTS operational_read_model_outbox_personalized_age_idx
    ON public.operational_read_model_outbox (created_at) WHERE personalized;

CREATE OR REPLACE FUNCTION public.buscar_pedidos_personalizados_projetados(
    p_prefix text, p_page integer DEFAULT 1, p_page_size integer DEFAULT 20
) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp AS $$
DECLARE v_ready boolean; v_result jsonb;
BEGIN
    IF p_prefix IS NULL OR p_prefix !~ '^[0-9]+$' THEN
        RAISE EXCEPTION 'p_prefix deve conter apenas dígitos';
    END IF;
    SELECT s.backfill_complete AND c.personalized_projection_enabled INTO v_ready
      FROM public.shopee_personalization_read_model_state s
      CROSS JOIN public.operational_read_model_config c
     WHERE s.singleton AND c.singleton;
    IF NOT COALESCE(v_ready, false) THEN
        RETURN jsonb_build_object('ready', false);
    END IF;
    WITH encontrados AS MATERIALIZED (
        SELECT id, data_pedido
          FROM public.shopee_personalization_read_model
         WHERE numero_pedido LIKE p_prefix || '%'
            OR numero_loja LIKE p_prefix || '%'
    ), pagina AS (
        SELECT id, data_pedido FROM encontrados
         ORDER BY data_pedido DESC, id DESC
         OFFSET (GREATEST(1, COALESCE(p_page, 1)) - 1)
                * LEAST(100, GREATEST(1, COALESCE(p_page_size, 20)))
         LIMIT LEAST(100, GREATEST(1, COALESCE(p_page_size, 20)))
    )
    SELECT jsonb_build_object(
        'ready', true,
        'rows', COALESCE((SELECT jsonb_agg(r.detalhes ORDER BY pagina.data_pedido DESC, pagina.id DESC)
                            FROM pagina JOIN public.shopee_personalization_read_model r USING (id)), '[]'::jsonb),
        'total', (SELECT count(*) FROM encontrados)
    ) INTO v_result;
    RETURN v_result;
END;
$$;
REVOKE ALL ON FUNCTION public.buscar_pedidos_personalizados_projetados(text, integer, integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.buscar_pedidos_personalizados_projetados(text, integer, integer)
    TO service_role;

-- The canonical view now includes Em Andamento, Produzido and Pronto para Envio.
-- Reopen the bounded backfill so older orders in the latter two states are included.
UPDATE public.shopee_personalization_read_model_state
   SET backfill_complete = false, updated_at = now()
 WHERE singleton;

-- Supabase's safe-update guard rejects unqualified DELETE in the original
-- rebuild function. That failure has kept the outbox and both read models
-- stalled in production. TRUNCATE replaces the complete small calendar tables
-- atomically inside the same transaction.
CREATE OR REPLACE FUNCTION public.rebuild_despacho_janelas_read_model()
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_inicio date := (now() AT TIME ZONE 'America/Sao_Paulo')::date;
    v_grupos integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('rebuild_despacho_janelas_read_model'));
    TRUNCATE TABLE public.despacho_janelas_read_model,
                   public.despacho_grupos_janelas_read_model;
    INSERT INTO public.despacho_grupos_janelas_read_model
        (integration_id, modalidade_id, data_inicio, data_fim)
    SELECT DISTINCT p.marketplace_integration_id, p.modalidade_logistica_id,
           v_inicio, v_inicio + 31
      FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.modalidade_logistica_id IS NOT NULL;
    GET DIAGNOSTICS v_grupos = ROW_COUNT;
    INSERT INTO public.despacho_janelas_read_model
        (integration_id, modalidade_id, dia, coleta_em, payload)
    SELECT g.integration_id, g.modalidade_id, d.dia::date, j.coleta_em, to_jsonb(j)
      FROM public.despacho_grupos_janelas_read_model g
      CROSS JOIN generate_series(v_inicio, v_inicio + 31, interval '1 day') d(dia)
      LEFT JOIN LATERAL public.janelas_logisticas(
          g.modalidade_id, g.integration_id, d.dia::date) j ON true;
    INSERT INTO public.despacho_janelas_read_model_state
        (singleton, data_inicio, data_fim, updated_at)
    VALUES (true, v_inicio, v_inicio + 31, now())
    ON CONFLICT (singleton) DO UPDATE SET
        data_inicio = EXCLUDED.data_inicio,
        data_fim = EXCLUDED.data_fim,
        updated_at = EXCLUDED.updated_at;
    RETURN v_grupos;
END;
$$;

CREATE OR REPLACE FUNCTION public.refresh_operational_read_models(p_limit integer DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    e record;
    v_ids integer[] := ARRAY[]::integer[];
    v_dispatch boolean := false;
    v_dispatch_calendar boolean := false;
    v_processed integer := 0;
    v_backfill_complete boolean;
    v_today date := (now() AT TIME ZONE 'America/Sao_Paulo')::date;
    v_started timestamptz;
    v_payload jsonb;
BEGIN
    SELECT backfill_complete INTO v_backfill_complete
      FROM public.shopee_personalization_read_model_state WHERE singleton;
    IF NOT COALESCE(v_backfill_complete, false)
       AND NOT EXISTS (SELECT 1 FROM public.operational_read_model_outbox WHERE backfill) THEN
        INSERT INTO public.operational_read_model_outbox(event_key, personalized, backfill)
        SELECT 'order:' || p.id, true, true FROM public.pedidos p
        JOIN public.canais_venda cv ON cv.id = p.canal_venda_id AND cv.slug = 'shopee'
        WHERE p.situacao_pedido_id IN (2, 3, 4)
          AND EXISTS (SELECT 1 FROM public.itens_pedido ip
                       WHERE ip.pedido_id = p.id AND ip.personalizado)
          AND NOT EXISTS (SELECT 1 FROM public.shopee_personalization_read_model r
                           WHERE r.id = p.id)
        ORDER BY p.id LIMIT 100
        ON CONFLICT (event_key) DO UPDATE SET personalized = true, backfill = true;
    END IF;

    FOR e IN SELECT * FROM public.operational_read_model_outbox
             ORDER BY created_at LIMIT LEAST(500, GREATEST(1, p_limit))
             FOR UPDATE SKIP LOCKED LOOP
        IF e.event_key LIKE 'order:%' THEN
            v_ids := array_append(v_ids, substring(e.event_key from 7)::integer);
        ELSIF e.event_key LIKE 'item:%' THEN
            v_ids := v_ids || ARRAY(SELECT pedido_id FROM public.itens_pedido
                                      WHERE id = substring(e.event_key from 6)::integer
                                        AND pedido_id IS NOT NULL);
        ELSIF e.event_key LIKE 'sn:%' THEN
            v_ids := v_ids || ARRAY(SELECT id FROM public.pedidos
                                      WHERE codigo_pedido_externo = substring(e.event_key from 4));
        ELSIF e.event_key LIKE 'user:%' THEN
            v_ids := v_ids || ARRAY(SELECT p.id FROM public.pedidos p
                                      JOIN public.canais_venda cv ON cv.id = p.canal_venda_id
                                                                    AND cv.slug = 'shopee'
                                     WHERE p.buyer_username = substring(e.event_key from 6)
                                       AND p.situacao_pedido_id IN (2, 3, 4));
        END IF;
        v_dispatch := v_dispatch OR e.dispatch;
        v_dispatch_calendar := v_dispatch_calendar OR e.dispatch_calendar;
        DELETE FROM public.operational_read_model_outbox WHERE event_key = e.event_key;
        v_processed := v_processed + 1;
    END LOOP;

    IF cardinality(v_ids) > 0 THEN
        PERFORM public.rebuild_shopee_personalization_read_model(
            ARRAY(SELECT DISTINCT unnest(v_ids)));
    END IF;

    -- The expensive completeness scan is only needed during initial backfill.
    IF NOT COALESCE(v_backfill_complete, false)
       AND NOT EXISTS (SELECT 1 FROM public.operational_read_model_outbox WHERE backfill)
       AND NOT EXISTS (SELECT 1 FROM public.operational_read_model_outbox
                        WHERE personalized AND created_at < now() - interval '10 seconds')
       AND NOT EXISTS (
           SELECT 1 FROM public.pedidos p
           JOIN public.canais_venda cv ON cv.id = p.canal_venda_id AND cv.slug = 'shopee'
           WHERE p.situacao_pedido_id IN (2, 3, 4)
             AND EXISTS (SELECT 1 FROM public.itens_pedido ip
                          WHERE ip.pedido_id = p.id AND ip.personalizado)
             AND NOT EXISTS (SELECT 1 FROM public.shopee_personalization_read_model r
                              WHERE r.id = p.id)
       ) THEN
        UPDATE public.shopee_personalization_read_model_state
           SET backfill_complete = true, updated_at = now() WHERE singleton;
    END IF;

    IF v_dispatch_calendar OR NOT EXISTS (
        SELECT 1 FROM public.despacho_janelas_read_model_state
         WHERE singleton AND data_inicio = v_today AND data_fim = v_today + 31
    ) THEN
        PERFORM public.rebuild_despacho_janelas_read_model();
    ELSIF v_dispatch AND EXISTS (
        SELECT 1 FROM public.vw_pedidos_pendentes_despacho p
         WHERE p.modalidade_logistica_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM public.despacho_grupos_janelas_read_model g
                WHERE COALESCE(g.integration_id, -1) = COALESCE(p.marketplace_integration_id, -1)
                  AND g.modalidade_id = p.modalidade_logistica_id
                  AND g.data_inicio = v_today AND g.data_fim = v_today + 31
           )
    ) THEN
        PERFORM public.rebuild_despacho_janelas_read_model();
    END IF;

    -- At most one expensive rebuild per four seconds, even while many orders
    -- change. The request path shares the same advisory lock.
    IF v_dispatch OR NOT EXISTS (
        SELECT 1 FROM public.despacho_contexto_read_model
         WHERE data = v_today AND refreshed_at > clock_timestamp() - interval '4 seconds'
    ) THEN
        PERFORM pg_advisory_xact_lock(hashtext('despacho_contexto:' || v_today::text));
        IF NOT EXISTS (
            SELECT 1 FROM public.despacho_contexto_read_model
             WHERE data = v_today AND refreshed_at > clock_timestamp() - interval '4 seconds'
        ) THEN
            v_started := clock_timestamp();
            v_payload := public.despacho_arvore_contexto_raw(v_today)
                || jsonb_build_object('snapshot_gerado_em', v_started);
            INSERT INTO public.despacho_contexto_read_model(data, payload, refreshed_at, valid_until)
            VALUES (v_today, v_payload, v_started, clock_timestamp() + interval '4 seconds')
            ON CONFLICT (data) DO UPDATE SET payload = EXCLUDED.payload,
                refreshed_at = EXCLUDED.refreshed_at, valid_until = EXCLUDED.valid_until;
        END IF;
    END IF;

    RETURN jsonb_build_object(
        'processed', v_processed,
        'orders', cardinality(v_ids),
        'backfill_pending', (SELECT count(*) FROM public.operational_read_model_outbox WHERE backfill)
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_arvore_contexto(p_data date)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_payload jsonb; v_started timestamptz;
BEGIN
    IF NOT (SELECT dispatch_snapshot_enabled FROM public.operational_read_model_config WHERE singleton) THEN
        v_started := clock_timestamp();
        RETURN public.despacho_arvore_contexto_raw(p_data)
            || jsonb_build_object('snapshot_gerado_em', v_started);
    END IF;
    SELECT payload INTO v_payload FROM public.despacho_contexto_read_model
     WHERE data = p_data AND refreshed_at > clock_timestamp() - interval '5 seconds';
    IF v_payload IS NOT NULL THEN RETURN v_payload; END IF;

    PERFORM pg_advisory_xact_lock(hashtext('despacho_contexto:' || p_data::text));
    SELECT payload INTO v_payload FROM public.despacho_contexto_read_model
     WHERE data = p_data AND refreshed_at > clock_timestamp() - interval '5 seconds';
    IF v_payload IS NOT NULL THEN RETURN v_payload; END IF;

    v_started := clock_timestamp();
    v_payload := public.despacho_arvore_contexto_raw(p_data)
        || jsonb_build_object('snapshot_gerado_em', v_started);
    INSERT INTO public.despacho_contexto_read_model(data, payload, refreshed_at, valid_until)
    VALUES (p_data, v_payload, v_started, clock_timestamp() + interval '4 seconds')
    ON CONFLICT (data) DO UPDATE SET payload = EXCLUDED.payload,
        refreshed_at = EXCLUDED.refreshed_at, valid_until = EXCLUDED.valid_until;
    RETURN v_payload;
END;
$$;
