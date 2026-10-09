-- Keep the last useful extraction visible while a newer chat context is
-- processed. A new context that yields no name or needs review must not erase
-- a name identified by an earlier successful execution.
CREATE OR REPLACE FUNCTION public.persist_mercadolivre_personalization_results(
    p_integration_id integer,
    p_pack_id text,
    p_context_hash text,
    p_status text,
    p_needs_review boolean,
    p_records jsonb,
    p_log jsonb,
    p_batch_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_record jsonb;
    v_pedido_id integer;
    v_item_id integer;
    v_rows integer := 0;
    v_log_pedido_id integer;
    v_log_ids jsonb := COALESCE(p_log->'pedido_ids', '[]'::jsonb);
    v_existing mercadolivre_personalizations%ROWTYPE;
    v_name text;
    v_initial text;
    v_status text;
    v_details jsonb;
BEGIN
    IF p_status NOT IN ('SUCCESS', 'NEEDS_REVIEW', 'NO_PERSONALIZATION_FOUND') THEN
        RAISE EXCEPTION 'invalid Mercado Livre personalization status';
    END IF;
    IF jsonb_typeof(p_records) <> 'array' OR jsonb_typeof(v_log_ids) <> 'array' THEN
        RAISE EXCEPTION 'personalization records and log order IDs must be arrays';
    END IF;

    FOR v_record IN SELECT value FROM jsonb_array_elements(p_records) LOOP
        v_pedido_id := (v_record->>'pedido_id')::integer;
        v_item_id := (v_record->>'item_pedido_id')::integer;
        IF NOT EXISTS (
            SELECT 1 FROM pedidos p
            JOIN itens_pedido i ON i.id = v_item_id AND i.pedido_id = p.id
            WHERE p.id = v_pedido_id
              AND p.marketplace_integration_id = p_integration_id
              AND p.marketplace_module_id = (
                  SELECT lower(ii.module_id) FROM installed_integrations ii
                   WHERE ii.id = p_integration_id
              )
        ) THEN
            RAISE EXCEPTION 'order/item does not belong to Mercado Livre integration %', p_integration_id;
        END IF;

        v_name := NULLIF(v_record->>'customization_name', '');
        v_initial := NULLIF(v_record->>'customization_initial', '');
        v_status := CASE WHEN p_needs_review THEN 'NEEDS_REVIEW' ELSE p_status END;
        v_details := COALESCE(v_record->'details', '{}'::jsonb);

        -- The most recent AI output may be inconclusive. Carry the last
        -- identified name forward, but retain review status and the new
        -- context/source metadata so the operator can see reprocessing state.
        IF v_name IS NULL AND v_initial IS NULL THEN
            SELECT * INTO v_existing
              FROM mercadolivre_personalizations
             WHERE marketplace_integration_id = p_integration_id
               AND pedido_id = v_pedido_id AND item_pedido_id = v_item_id
               AND pack_id = p_pack_id
               AND (status = 'SUCCESS' OR confirmed = TRUE)
               AND (NULLIF(btrim(customization_name), '') IS NOT NULL
                    OR NULLIF(btrim(customization_initial), '') IS NOT NULL)
             ORDER BY updated_at DESC, id DESC
             LIMIT 1;
            IF FOUND THEN
                v_name := v_existing.customization_name;
                v_initial := v_existing.customization_initial;
                v_details := COALESCE(v_existing.details, '{}'::jsonb) || v_details ||
                    jsonb_build_object('previous_context_hash', v_existing.context_hash,
                                       'reprocessed_context_hash', p_context_hash);
            END IF;
        END IF;

        INSERT INTO mercadolivre_personalizations (
            marketplace_integration_id, pedido_id, item_pedido_id, pack_id,
            provider_order_id, provider_item_id, provider_message_id,
            quantity_to_personalize, customization_name, customization_initial,
            status, reasoning, context_hash, source, confirmed, details
        ) VALUES (
            p_integration_id, v_pedido_id, v_item_id, p_pack_id,
            v_record->>'provider_order_id', COALESCE(v_record->>'provider_item_id', 'local-item-' || v_item_id::text),
            v_record->>'provider_message_id', GREATEST(1, COALESCE((v_record->>'quantity_to_personalize')::integer, 1)),
            v_name, v_initial, v_status, v_record->>'reasoning', p_context_hash, 'ai', FALSE, v_details
        ) ON CONFLICT (marketplace_integration_id, pedido_id, item_pedido_id, provider_item_id, context_hash)
        DO UPDATE SET provider_message_id = EXCLUDED.provider_message_id,
                      quantity_to_personalize = EXCLUDED.quantity_to_personalize,
                      customization_name = COALESCE(EXCLUDED.customization_name,
                                                    mercadolivre_personalizations.customization_name),
                      customization_initial = COALESCE(EXCLUDED.customization_initial,
                                                       mercadolivre_personalizations.customization_initial),
                      status = EXCLUDED.status, reasoning = EXCLUDED.reasoning,
                      source = 'ai', confirmed = mercadolivre_personalizations.confirmed,
                      confirmed_by = mercadolivre_personalizations.confirmed_by,
                      confirmed_at = mercadolivre_personalizations.confirmed_at,
                      details = EXCLUDED.details, updated_at = now();
        v_rows := v_rows + 1;
    END LOOP;

    UPDATE mercadolivre_chat_conversations
       SET context_hash = p_context_hash,
           ai_status = CASE WHEN p_needs_review THEN 'needs_review' ELSE lower(p_status) END,
           needs_review = p_needs_review OR p_status = 'NEEDS_REVIEW',
           last_ai_executed_at = now(), last_error = NULL, updated_at = now()
     WHERE marketplace_integration_id = p_integration_id AND pack_id = p_pack_id;

    FOR v_log_pedido_id IN
        SELECT DISTINCT (value #>> '{}')::integer FROM jsonb_array_elements(v_log_ids)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pedidos p WHERE p.id = v_log_pedido_id
                       AND p.marketplace_integration_id = p_integration_id) THEN
            RAISE EXCEPTION 'log order does not belong to Mercado Livre integration %', p_integration_id;
        END IF;
        INSERT INTO mercadolivre_personalization_logs (
            marketplace_integration_id, batch_id, pack_id, pedido_id, status,
            input_data, model_result, metadata
        ) VALUES (
            p_integration_id, p_batch_id, p_pack_id, v_log_pedido_id, lower(p_status),
            p_log->>'input_data', p_log->'model_result', COALESCE(p_log->'metadata', '{}'::jsonb)
        );
    END LOOP;
    IF jsonb_array_length(v_log_ids) = 0 THEN
        INSERT INTO mercadolivre_personalization_logs (
            marketplace_integration_id, batch_id, pack_id, status, input_data, model_result, metadata
        ) VALUES (p_integration_id, p_batch_id, p_pack_id, lower(p_status),
                  p_log->>'input_data', p_log->'model_result', COALESCE(p_log->'metadata', '{}'::jsonb));
    END IF;
    RETURN jsonb_build_object('saved', v_rows, 'status', p_status, 'context_hash', p_context_hash);
END;
$$;
