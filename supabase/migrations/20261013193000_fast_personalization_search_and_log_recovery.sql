-- Fast indexed prefix lookups for Shopee personalized orders.
CREATE INDEX IF NOT EXISTS idx_pedidos_numero_pedido_prefix
    ON public.pedidos (numero_pedido text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_pedidos_codigo_externo_prefix
    ON public.pedidos (codigo_pedido_externo text_pattern_ops);

CREATE OR REPLACE FUNCTION public.search_personalized_shopee_order_ids(
    p_prefix text,
    p_page integer DEFAULT 1,
    p_page_size integer DEFAULT 20
)
RETURNS TABLE (id integer, total_count bigint)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    IF p_prefix IS NULL OR p_prefix !~ '^[0-9]+$' THEN
        RAISE EXCEPTION 'p_prefix deve conter apenas dígitos';
    END IF;

    RETURN QUERY
    WITH eligible_orders AS (
        SELECT p.id, p.data_venda
          FROM public.pedidos AS p
          JOIN public.canais_venda AS cv ON cv.id = p.canal_venda_id
         WHERE cv.slug = 'shopee'
           AND p.situacao_pedido_id = ANY (ARRAY[2, 3, 4])
           AND (
               p.numero_pedido LIKE p_prefix || '%'
               OR p.codigo_pedido_externo LIKE p_prefix || '%'
           )
           AND EXISTS (
               SELECT 1
                 FROM public.itens_pedido AS ip
                WHERE ip.pedido_id = p.id
                  AND ip.personalizado = true
           )
    )
    SELECT eligible_orders.id, count(*) OVER ()
      FROM eligible_orders
     ORDER BY eligible_orders.data_venda DESC, eligible_orders.id DESC
     OFFSET (GREATEST(1, COALESCE(p_page, 1)) - 1)
            * LEAST(100, GREATEST(1, COALESCE(p_page_size, 20)))
     LIMIT LEAST(100, GREATEST(1, COALESCE(p_page_size, 20)));
END;
$$;

REVOKE ALL ON FUNCTION public.search_personalized_shopee_order_ids(text, integer, integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.search_personalized_shopee_order_ids(text, integer, integer)
    TO service_role;

-- Keep the direct processing path's replacement records and success log in a
-- single database transaction, matching the batch-worker persistence path.
CREATE OR REPLACE FUNCTION public.persist_shopee_personalization_result(
    p_shopee_order_sn text,
    p_personalizations jsonb,
    p_log jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NULLIF(trim(p_shopee_order_sn), '') IS NULL THEN
        RAISE EXCEPTION 'shopee_order_sn obrigatório';
    END IF;

    DELETE FROM public.personalizacoes_pedido
     WHERE shopee_order_sn = p_shopee_order_sn;

    INSERT INTO public.personalizacoes_pedido (
        codigo_pedido, shopee_order_sn, bling_id, item_pedido_id, item_id,
        item_description, customization_name, customization_initial,
        name_source_message_id, status, reasoning, detalhes_personalizacao,
        metadata, updated_at
    )
    SELECT codigo_pedido, shopee_order_sn, bling_id, item_pedido_id, item_id,
           item_description, customization_name, customization_initial,
           name_source_message_id, status, reasoning, detalhes_personalizacao,
           metadata, updated_at
      FROM jsonb_populate_recordset(
          NULL::public.personalizacoes_pedido,
          COALESCE(p_personalizations, '[]'::jsonb)
      );

    IF p_log IS NOT NULL THEN
        INSERT INTO public.logs_execucao_ia (
            order_sn, executed_at, input_data, chat_context,
            extracted_personalization, model_result, status, error_message, metadata
        )
        SELECT order_sn, executed_at, input_data, chat_context,
               extracted_personalization, model_result, status, error_message, metadata
          FROM jsonb_populate_record(NULL::public.logs_execucao_ia, p_log);
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.persist_shopee_personalization_result(text, jsonb, jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.persist_shopee_personalization_result(text, jsonb, jsonb)
    TO service_role;

-- Return the saved records first; if absent, recover identified data from the
-- latest successful execution log. A later successful empty result stays empty.
CREATE OR REPLACE FUNCTION public.personalizacoes_para_item(
    p_item_pedido_id integer,
    p_shopee_order_sn text,
    p_item_description text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_records jsonb;
    v_log_items jsonb;
    v_fallback jsonb;
BEGIN
    SELECT jsonb_agg(jsonb_build_object(
               'id', pp.id,
               'item_pedido_id', pp.item_pedido_id,
               'item_id', pp.item_id,
               'item_description', pp.item_description,
               'quantity_to_personalize', COALESCE(
                   CASE WHEN pp.detalhes_personalizacao ->> 'quantity_to_personalize' ~ '^[0-9]+$'
                        THEN (pp.detalhes_personalizacao ->> 'quantity_to_personalize')::integer END,
                   CASE WHEN pp.metadata ->> 'quantity_to_personalize' ~ '^[0-9]+$'
                        THEN (pp.metadata ->> 'quantity_to_personalize')::integer END,
                   1
               ),
               'customization_name', pp.customization_name,
               'name_source_message_id', pp.name_source_message_id,
               'customization_initial', pp.customization_initial,
               'initial_source_message_id', COALESCE(
                   pp.detalhes_personalizacao ->> 'initial_source_message_id',
                   pp.metadata ->> 'initial_source_message_id'
               ),
               'status', pp.status,
               'reasoning', pp.reasoning
           ) ORDER BY pp.id)
      INTO v_records
      FROM public.personalizacoes_pedido AS pp
     WHERE pp.item_pedido_id = p_item_pedido_id
        OR (pp.item_pedido_id IS NULL
            AND pp.shopee_order_sn = p_shopee_order_sn
            AND pp.item_description = p_item_description);

    IF v_records IS NOT NULL THEN
        RETURN v_records;
    END IF;

    SELECT CASE WHEN jsonb_typeof(l.extracted_personalization) = 'array'
                THEN l.extracted_personalization ELSE '[]'::jsonb END
      INTO v_log_items
      FROM public.logs_execucao_ia AS l
     WHERE l.order_sn = p_shopee_order_sn
       AND lower(COALESCE(l.status, '')) = 'success'
     ORDER BY l.executed_at DESC, l.id DESC
     LIMIT 1;

    IF v_log_items IS NULL THEN
        RETURN '[]'::jsonb;
    END IF;

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'id', NULL,
               'item_pedido_id', p_item_pedido_id,
               'item_id', entry.value ->> 'item_id',
               'item_description', entry.value ->> 'item_description',
               'quantity_to_personalize', COALESCE(
                   CASE WHEN entry.value ->> 'quantity_to_personalize' ~ '^[0-9]+$'
                        THEN (entry.value ->> 'quantity_to_personalize')::integer END,
                   1
               ),
               'customization_name', entry.value ->> 'customization_name',
               'name_source_message_id', entry.value ->> 'name_source_message_id',
               'customization_initial', entry.value ->> 'customization_initial',
               'initial_source_message_id', entry.value ->> 'initial_source_message_id',
               'status', COALESCE(entry.value ->> 'status', 'SUCCESS'),
               'reasoning', NULL
           ) ORDER BY entry.ordinality), '[]'::jsonb)
      INTO v_fallback
      FROM jsonb_array_elements(v_log_items) WITH ORDINALITY AS entry(value, ordinality)
     WHERE (
           NULLIF(trim(entry.value ->> 'item_description'), '') = NULLIF(trim(p_item_description), '')
           OR entry.value ->> 'item_id' = p_item_pedido_id::text
       )
       AND (
           NULLIF(trim(entry.value ->> 'customization_name'), '') IS NOT NULL
           OR NULLIF(trim(entry.value ->> 'customization_initial'), '') IS NOT NULL
       );

    RETURN v_fallback;
END;
$$;

REVOKE ALL ON FUNCTION public.personalizacoes_para_item(integer, text, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.personalizacoes_para_item(integer, text, text)
    TO service_role;

CREATE OR REPLACE VIEW public.view_vendas_personalizadas_v3
WITH (security_invoker = true) AS
SELECT v.id,
       v.numero_pedido,
       v.numero_loja,
       v.data_pedido,
       v.contato,
       v.nome_cliente,
       v.bling_id,
       v.personalizado,
       v.deletado,
       v.informacoes_comprador,
       v.shopee_message,
       v.buyer_username,
       v.has_chat_messages,
       v.has_buyer_message,
       v.last_chat_message_at,
       v.last_buyer_message_at,
       v.last_ai_executed_at,
       v.ai_status,
       v.needs_ai_processing,
       COALESCE((
           SELECT jsonb_agg(
                      CASE
                          WHEN jsonb_typeof(item.value -> 'personalizations') = 'array'
                               AND jsonb_array_length(item.value -> 'personalizations') > 0
                          THEN item.value
                          ELSE jsonb_set(
                              item.value,
                              '{personalizations}',
                              public.personalizacoes_para_item(
                                  NULLIF(item.value ->> 'id', '')::integer,
                                  v.numero_loja,
                                  item.value ->> 'descricao'
                              ),
                              true
                          )
                      END
                      ORDER BY item.ordinality
                  )
             FROM jsonb_array_elements(
                      CASE WHEN jsonb_typeof(v.itens) = 'array'
                           THEN v.itens ELSE '[]'::jsonb END
                  ) WITH ORDINALITY AS item(value, ordinality)
       ), '[]'::jsonb) AS itens
  FROM public.view_pedidos_personalizados_ai AS v;

GRANT SELECT ON public.view_vendas_personalizadas_v3 TO service_role;

-- Backfill missing table records from the latest successful log without
-- replacing or duplicating existing saved personalizations.
WITH latest_success AS (
    SELECT DISTINCT ON (l.order_sn)
           l.order_sn, l.executed_at, l.extracted_personalization,
           l.model_result, l.metadata
      FROM public.logs_execucao_ia AS l
     WHERE lower(COALESCE(l.status, '')) = 'success'
     ORDER BY l.order_sn, l.executed_at DESC, l.id DESC
), extracted AS (
    SELECT l.*, entry.value AS personalization
      FROM latest_success AS l
      CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(l.extracted_personalization) = 'array'
               THEN l.extracted_personalization ELSE '[]'::jsonb END
      ) AS entry(value)
), mapped AS (
    SELECT p.codigo_pedido_externo AS shopee_order_sn,
           e.executed_at,
           e.metadata,
           e.model_result,
           e.personalization,
           item.id AS item_pedido_id,
           row_number() OVER (
               PARTITION BY p.codigo_pedido_externo, e.personalization
               ORDER BY (item.id::text = e.personalization ->> 'item_id') DESC, item.id
           ) AS match_rank
      FROM extracted AS e
      JOIN public.pedidos AS p
        ON p.codigo_pedido_externo = e.order_sn
      JOIN public.canais_venda AS cv
        ON cv.id = p.canal_venda_id AND cv.slug = 'shopee'
      JOIN LATERAL (
          SELECT ip.id
            FROM public.itens_pedido AS ip
           WHERE ip.pedido_id = p.id
             AND ip.personalizado = true
             AND (
                 ip.id::text = e.personalization ->> 'item_id'
                 OR ip.descricao = e.personalization ->> 'item_description'
             )
           ORDER BY (ip.id::text = e.personalization ->> 'item_id') DESC, ip.id
           LIMIT 1
      ) AS item ON true
     WHERE NULLIF(trim(e.personalization ->> 'customization_name'), '') IS NOT NULL
        OR NULLIF(trim(e.personalization ->> 'customization_initial'), '') IS NOT NULL
)
INSERT INTO public.personalizacoes_pedido (
    codigo_pedido, shopee_order_sn, item_pedido_id, item_id, item_description,
    customization_name, customization_initial, name_source_message_id, status,
    reasoning, detalhes_personalizacao, metadata, updated_at
)
SELECT mapped.shopee_order_sn,
       mapped.shopee_order_sn,
       mapped.item_pedido_id,
       mapped.personalization ->> 'item_id',
       mapped.personalization ->> 'item_description',
       mapped.personalization ->> 'customization_name',
       mapped.personalization ->> 'customization_initial',
       mapped.personalization ->> 'name_source_message_id',
       COALESCE(mapped.personalization ->> 'status', 'SUCCESS'),
       mapped.model_result ->> 'reasoning',
       jsonb_build_object(
           'quantity_to_personalize',
           CASE WHEN mapped.personalization ->> 'quantity_to_personalize' ~ '^[0-9]+$'
                THEN (mapped.personalization ->> 'quantity_to_personalize')::integer
                ELSE 1 END,
           'initial_source_message_id', mapped.personalization ->> 'initial_source_message_id'
       ),
       jsonb_build_object(
           'source', COALESCE(mapped.metadata ->> 'model_used', mapped.metadata ->> 'model_name', 'ai_log_recovery'),
           'recovered_from_log', true,
           'processed_at', mapped.executed_at
       ),
       mapped.executed_at AT TIME ZONE 'UTC'
  FROM mapped
 WHERE mapped.match_rank = 1
   AND NOT EXISTS (
       SELECT 1
         FROM public.personalizacoes_pedido AS pp
        WHERE pp.shopee_order_sn = mapped.shopee_order_sn
          AND pp.item_pedido_id = mapped.item_pedido_id
          AND (
              (mapped.personalization ->> 'name_source_message_id') IS NOT NULL
              AND pp.name_source_message_id = mapped.personalization ->> 'name_source_message_id'
              OR pp.customization_name IS NOT DISTINCT FROM mapped.personalization ->> 'customization_name'
                 AND pp.customization_initial IS NOT DISTINCT FROM mapped.personalization ->> 'customization_initial'
          )
   );
